#!/usr/bin/env python3
"""
DecisionSynth Bench — Zep / Graphiti adapter (maintainer-run vendor row).

Pipeline under measurement: Graphiti's temporal knowledge graph (entity +
relationship extraction, edge facts, hybrid retrieval with reranking) —
the open-source engine behind Zep's memory layer. Each decision episode
is rendered as a plain-text decision memo and ingested with
`add_episode_bulk` (Graphiti's corpus-ingest path). Tasks are answered
from Graphiti search results ONLY: the answer LLM sees the retrieved
edge facts plus the episode ids of the episodic nodes each fact was
extracted from (provenance Graphiti stores natively) — never the raw
episode corpus.

Run configuration (published with the scoreboard row per adapters/README
rule 3):
  - graphiti-core 0.29.2 + Neo4j 5.26 (docker, default config)
  - LLM: gemini-2.5-flash, temperature 0 (extraction AND answer
    generation); reranker: GeminiRerankerClient(gemini-3.1-flash-lite)
  - Embedder: gemini-embedding-001 (Graphiti default dims)
  - Retrieval: `Graphiti.search(question, num_results=25)` (hybrid
    cosine + BM25 + reranker); evidence_ids = first-seen order of
    source-episode ids over ranked edge facts
  - Single group_id ("decisionsynth-corpus"), firm-wide decision log.

Usage:
  python bench/adapters/zep_graphiti.py <episodes.json> <qa.json> <out-answers.json> \
      [--k 5] [--data-dir .graphiti-bench] [--search-limit 25] [--bulk-chunk 16] \
      [--neo4j-uri bolt://localhost:7687] [--neo4j-user neo4j] [--neo4j-pass ...]

Requires: GEMINI_API_KEY, a running Neo4j. `pip install graphiti-core[google-genai]`.
Ingest and answering both checkpoint; rerunning resumes.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

LLM_MODEL = "gemini-2.5-flash"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
SMALL_MODEL = "gemini-3.1-flash-lite"
EMBED_MODEL = "gemini-embedding-001"
DEFAULT_GROUP_ID = "decisionsynth-corpus"
SYSTEM_NAME = "zep-graphiti"


# ── episode → decision-memo text (identical rendering across all vendor adapters) ──
def render_episode(e: dict) -> str:
    hh = e["household_ref"]
    lines = [
        f"Decision episode {e['episode_id']} — household {hh['archetype_id']} (seed {hh['seed']}), month {e['month_index']}.",
        f"Decision type: {e['decision_type']}.",
    ]
    trig = e.get("trigger", {})
    ev = trig.get("evidence", {})
    metrics = ev.get("derived_metrics", {})
    metrics_txt = ", ".join(f"{k}={v}" for k, v in metrics.items())
    trig_txt = f"Trigger: {trig.get('kind', 'unknown')}"
    if trig.get("event_type"):
        trig_txt += f" event '{trig['event_type']}'"
    if metrics_txt:
        trig_txt += f" (metrics: {metrics_txt})"
    lines.append(trig_txt + ".")
    if e.get("semantic_refs"):
        lines.append("Cited reference figures: " + ", ".join(e["semantic_refs"]) + ".")
    pp = e.get("procedural_path", {})
    opts = []
    for o in pp.get("options_considered", []):
        s = o.get("option", "?")
        if o.get("permitted") is False:
            s += " (blocked by " + ", ".join(o.get("blocking_refs", [])) + ")"
        opts.append(s)
    lines.append(
        f"Policy applied: {pp.get('policy', '?')}; options considered: {'; '.join(opts) or 'n/a'}; "
        f"recommended option: {pp.get('recommended_option', '?')}; terminal step: {pp.get('terminal_step', '?')}."
    )
    res = e.get("resolution", {})
    res_txt = (
        f"Resolution: followed policy: {'yes' if res.get('followed_policy') else 'NO'}; "
        f"outcome: {res.get('outcome', '?')}; outcome status: {res.get('outcome_status', '?')}"
    )
    if res.get("override_reason"):
        res_txt += f"; override reason: {res['override_reason']}"
    op = res.get("outcome_params")
    if op:
        res_txt += "; params: " + ", ".join(f"{k}={json.dumps(v)}" for k, v in op.items())
    lines.append(res_txt + ".")
    if e.get("lineage"):
        lines.append("Lineage (prior related episodes): " + ", ".join(e["lineage"]) + ".")
    return "\n".join(lines)


def month_to_datetime(month_index: int) -> datetime:
    # Deterministic synthetic timeline: month 1 → 2018-01-01.
    year = 2018 + (month_index - 1) // 12
    month = (month_index - 1) % 12 + 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


# ── answer generation from retrieved memory content (Gemini structured output) ──
ANSWER_SCHEMAS = {
    "direct_recall": {
        "type": "OBJECT",
        "properties": {"outcome": {"type": "STRING"}, "outcome_status": {"type": "STRING"}},
        "required": ["outcome", "outcome_status"],
    },
    "rationale_lookup": {
        "type": "OBJECT",
        "properties": {
            "override_reason": {"type": "STRING", "nullable": True},
            "trigger_event_type": {"type": "STRING", "nullable": True},
            "recommended_option": {"type": "STRING"},
        },
        "required": ["override_reason", "trigger_event_type", "recommended_option"],
    },
    "rule_attribution": {
        "type": "OBJECT",
        "properties": {"semantic_refs": {"type": "ARRAY", "items": {"type": "STRING"}}},
        "required": ["semantic_refs"],
    },
    "temporal_ordering": {
        "type": "OBJECT",
        "properties": {"episode_ids": {"type": "ARRAY", "items": {"type": "STRING"}}},
        "required": ["episode_ids"],
    },
    "precedent_search": {
        "type": "OBJECT",
        "properties": {
            "episodes": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "episode_id": {"type": "STRING"},
                        "outcome_status": {"type": "STRING"},
                    },
                    "required": ["episode_id", "outcome_status"],
                },
            }
        },
        "required": ["episodes"],
    },
}

TYPE_INSTRUCTIONS = {
    "direct_recall": (
        "Report the decision's recorded outcome (the exact outcome identifier, e.g. "
        "'partial_roth_conversion') and its outcome_status (e.g. 'approved'), exactly as stored."
    ),
    "rationale_lookup": (
        "Report the override_reason recorded for the decision (null only if none is stored), the "
        "trigger event type — the specific event identifier such as 'major_illness' or 'job_loss', "
        "NOT the trigger kind ('life_event', 'stress_event', 'cash_flow'); null if the trigger has "
        "no event type — and the option the policy recommended. Use the exact stored identifiers."
    ),
    "rule_attribution": (
        "Report the full list of cited reference figures (semantic_refs, dotted identifiers like "
        "'tax.income_brackets.mfj') that governed the decision — all of them, exactly as stored."
    ),
    "temporal_ordering": (
        "List the episode_ids of the SAME household's decision episodes that happened BEFORE the "
        "anchor decision named in the question, within the 24 months prior, in chronological order "
        "(earliest first). Exclude the anchor itself. Episode ids look like 'D1-A-02-seed-2-m5'."
    ),
    "precedent_search": (
        "List every episode matching the question's decision type and override reason, as "
        "{episode_id, outcome_status} objects. Only include episodes the memories support."
    ),
}


def make_answer_fn(provider: str, api_key: str):
    """provider: which model family CREATES answers ('gemini' or 'anthropic')."""
    if provider == "anthropic":
        import anthropic as _anthropic

        aclient = _anthropic.Anthropic(api_key=api_key)
    else:
        from google import genai
        from google.genai import types as gtypes

        client = genai.Client(api_key=api_key)

    def generate(task: dict, memories: list) -> dict:
        ctx_lines = []
        for i, m in enumerate(memories, 1):
            tag = f" [episode_ids: {', '.join(m['episode_ids'])}]" if m.get("episode_ids") else ""
            ctx_lines.append(f"{i}.{tag} {m['text']}")
        prompt = (
            "You are answering a question about a financial-advisory decision log using ONLY the "
            "retrieved memory entries below. If the memories do not contain the answer, give your "
            "best guess from what they do contain.\n\n"
            f"Question: {task['question']}\n\n"
            f"Retrieved memories:\n" + ("\n".join(ctx_lines) or "(none)") + "\n\n"
            f"Instructions: {TYPE_INSTRUCTIONS[task['task_type']]}"
        )
        for attempt in range(6):
            try:
                if provider == "anthropic":
                    msg = aclient.messages.create(
                        model=ANTHROPIC_MODEL,
                        max_tokens=2048,
                        temperature=0.0,
                        messages=[{
                            "role": "user",
                            "content": prompt
                            + "\n\nRespond with ONLY a JSON object matching this schema "
                            + "(no prose, no code fences): "
                            + json.dumps(ANSWER_SCHEMAS[task["task_type"]]),
                        }],
                    )
                    text = msg.content[0].text.strip()
                    if text.startswith("```"):
                        text = text.strip("`\n")
                        if text.startswith("json"):
                            text = text[4:]
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        obj, _ = json.JSONDecoder().raw_decode(text.lstrip())
                        return obj
                resp = client.models.generate_content(
                    model=LLM_MODEL,
                    contents=prompt,
                    config=gtypes.GenerateContentConfig(
                        temperature=0.0,
                        response_mime_type="application/json",
                        response_schema=ANSWER_SCHEMAS[task["task_type"]],
                        thinking_config=gtypes.ThinkingConfig(thinking_budget=0),
                    ),
                )
                if resp.text is None:
                    raise ValueError("empty model response")
                return json.loads(resp.text)
            except Exception as exc:  # noqa: BLE001 — retry transient API errors
                if attempt == 5:
                    raise
                wait = min(2 ** attempt * 2, 60)
                if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
                    wait = max(wait, 15)
                time.sleep(wait)
        return {}

    return generate


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("episodes")
    ap.add_argument("qa")
    ap.add_argument("out")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--llm", choices=["gemini", "anthropic"], default="gemini", help="model family that CREATES (extraction where applicable + answers)")
    ap.add_argument("--data-dir", default=".graphiti-bench")
    ap.add_argument("--search-limit", type=int, default=25)
    ap.add_argument("--bulk-chunk", type=int, default=16)
    ap.add_argument("--answer-concurrency", type=int, default=6)
    ap.add_argument("--group-id", default=DEFAULT_GROUP_ID)
    ap.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-pass", default=os.environ.get("NEO4J_PASSWORD", "benchpass123"))
    args = ap.parse_args()

    group_id = args.group_id
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY is required")

    from google.genai import types as gtypes

    from graphiti_core import Graphiti
    from graphiti_core.cross_encoder.gemini_reranker_client import GeminiRerankerClient
    from graphiti_core.embedder.gemini import GeminiEmbedder, GeminiEmbedderConfig
    from graphiti_core.llm_client.config import LLMConfig
    from graphiti_core.llm_client.gemini_client import GeminiClient
    from graphiti_core.nodes import EpisodeType
    from graphiti_core.utils.bulk_utils import RawEpisode

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if args.llm == "anthropic" and not anthropic_key:
        sys.exit("ANTHROPIC_API_KEY is required with --llm anthropic")
    create_key = anthropic_key if args.llm == "anthropic" else api_key
    if args.llm == "anthropic":
        from graphiti_core.llm_client.anthropic_client import AnthropicClient

        llm_client = AnthropicClient(
            config=LLMConfig(api_key=anthropic_key, model=ANTHROPIC_MODEL, small_model=ANTHROPIC_MODEL, temperature=0.0)
        )
    else:
        llm_client = GeminiClient(
            config=LLMConfig(api_key=api_key, model=LLM_MODEL, small_model=SMALL_MODEL, temperature=0.0),
            thinking_config=gtypes.ThinkingConfig(thinking_budget=0),
        )
    graphiti = Graphiti(
        args.neo4j_uri,
        args.neo4j_user,
        args.neo4j_pass,
        llm_client=llm_client,
        embedder=GeminiEmbedder(config=GeminiEmbedderConfig(api_key=api_key, embedding_model=EMBED_MODEL)),
        cross_encoder=GeminiRerankerClient(config=LLMConfig(api_key=api_key, model=SMALL_MODEL)),
    )
    await graphiti.build_indices_and_constraints()

    episodes = json.loads(Path(args.episodes).read_text())["episodes"]
    tasks = json.loads(Path(args.qa).read_text())["qa_tasks"]

    # ── ingest (checkpointed, bulk chunks) ──
    done_path = data_dir / "ingested.json"
    done = set(json.loads(done_path.read_text())) if done_path.exists() else set()
    todo = [e for e in episodes if e["episode_id"] not in done]
    print(f"[graphiti] ingest: {len(done)} done, {len(todo)} to go", flush=True)

    for i in range(0, len(todo), args.bulk_chunk):
        chunk = todo[i : i + args.bulk_chunk]
        raw = [
            RawEpisode(
                name=e["episode_id"],
                content=render_episode(e),
                source=EpisodeType.text,
                source_description="DecisionSynth advisory decision log",
                reference_time=month_to_datetime(e["month_index"]),
            )
            for e in chunk
        ]
        for attempt in range(8):
            try:
                await graphiti.add_episode_bulk(raw, group_id=group_id)
                break
            except Exception as exc:  # noqa: BLE001 — retry transient API errors
                if attempt == 7:
                    raise
                wait = min(2 ** attempt * 10, 300)
                if "RateLimit" in type(exc).__name__ or "429" in str(exc):
                    wait = max(wait, 90)
                print(f"[graphiti] bulk chunk retry in {wait}s after: {exc!r}", flush=True)
                await asyncio.sleep(wait)
        done.update(e["episode_id"] for e in chunk)
        done_path.write_text(json.dumps(sorted(done)))
        print(f"[graphiti] ingested {len(done)}/{len(episodes)}", flush=True)

    # ── map episodic-node uuid → episode_id (provenance for evidence_ids) ──
    records, _, _ = await graphiti.driver.execute_query(
        "MATCH (e:Episodic {group_id: $g}) RETURN e.uuid AS uuid, e.name AS name", g=group_id
    )
    uuid_to_eid = {r["uuid"]: r["name"] for r in records}
    print(f"[graphiti] {len(uuid_to_eid)} episodic nodes in graph", flush=True)

    # ── answer (checkpointed) ──
    partial_path = data_dir / f"answers-partial-{args.llm}-{Path(args.qa).stem}.json"
    answers = json.loads(partial_path.read_text()) if partial_path.exists() else {}
    todo_tasks = [t for t in tasks if t["task_id"] not in answers]
    print(f"[graphiti] answering: {len(answers)} done, {len(todo_tasks)} to go", flush=True)
    generate = make_answer_fn(args.llm, create_key)
    sem = asyncio.Semaphore(args.answer_concurrency)
    write_lock = asyncio.Lock()
    counter = {"n": 0}

    async def answer_one(task: dict) -> None:
        try:
            await _answer_one_inner(task)
        except Exception as exc:  # noqa: BLE001 — skip failed task, keep the run alive
            print(f"[graphiti] task failed ({task['task_id']}): {exc}", flush=True)

    async def _answer_one_inner(task: dict) -> None:
        clean = {"task_id": task["task_id"], "task_type": task["task_type"], "question": task["question"]}
        async with sem:
            edges = None
            for attempt in range(5):
                try:
                    edges = await graphiti.search(
                        clean["question"], group_ids=[group_id], num_results=args.search_limit
                    )
                    break
                except Exception:  # noqa: BLE001 — retry transient API errors
                    if attempt == 4:
                        raise
                    await asyncio.sleep(min(2 ** attempt * 3, 45))
            evidence, seen, mems = [], set(), []
            for edge in edges:
                eids = [uuid_to_eid[u] for u in (edge.episodes or []) if u in uuid_to_eid]
                for eid in eids:
                    if eid not in seen:
                        seen.add(eid)
                        evidence.append(eid)
                valid = f" (valid_at: {edge.valid_at.date()})" if getattr(edge, "valid_at", None) else ""
                mems.append({"episode_ids": eids, "text": (edge.fact or "") + valid})
            answer_key = await asyncio.to_thread(generate, clean, mems)
        async with write_lock:
            answers[clean["task_id"]] = {
                "task_id": clean["task_id"],
                "evidence_ids": evidence,
                "answer_key": answer_key,
                "_context": mems,
            }
            counter["n"] += 1
            if counter["n"] % 50 == 0 or counter["n"] == len(todo_tasks):
                partial_path.write_text(json.dumps(answers))
                print(f"[graphiti] answered {len(answers)}/{len(tasks)}", flush=True)

    await asyncio.gather(*(answer_one(t) for t in todo_tasks))

    system = SYSTEM_NAME if args.llm == "gemini" else f"{SYSTEM_NAME}@{ANTHROPIC_MODEL}"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    contexts = {tid: a.get("_context", []) for tid, a in answers.items()}
    Path(str(out) + ".contexts.json").write_text(json.dumps(contexts))
    ordered = [
        {k: v for k, v in answers[t["task_id"]].items() if k != "_context"}
        for t in tasks
        if t["task_id"] in answers
    ]
    out.write_text(json.dumps({"system": system, "answers": ordered}, indent=2) + "\n")
    print(f"[graphiti] {SYSTEM_NAME}: answered {len(ordered)} tasks over {len(episodes)} episodes → {out}", flush=True)
    await graphiti.close()


if __name__ == "__main__":
    asyncio.run(main())
