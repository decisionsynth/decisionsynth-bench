#!/usr/bin/env python3
"""
DecisionSynth Bench — Letta adapter (maintainer-run vendor row).

Pipeline under measurement: Letta's self-hosted server with archival
memory (passage store + embedding search). Each decision episode is
rendered as a plain-text decision memo and inserted as one archival
passage (`passages.create`, Letta's data-ingest path for external
corpora), tagged with its episode_id and stamped with the synthetic
timeline date. Tasks are answered from `passages.search` results ONLY:
the answer LLM sees the retrieved passage texts (plus each passage's
episode_id tag, provenance Letta stores natively) — never the raw
episode corpus.

Note: Letta archival passages store text verbatim (chunked), so unlike
extraction-based pipelines this row measures Letta's retrieval quality
more than compression loss; core-memory/sleep-time compression is not
exercised. Disclosed with the scoreboard row.

Run configuration (published with the scoreboard row per adapters/README
rule 3):
  - letta/letta:latest docker image (server 0.16.8), letta-client (pip)
  - Agent: model google_ai/gemini-2.5-flash (BYOK google_ai provider);
    embedding gemini-embedding-001 (3072 dims) via Google's
    OpenAI-compatible endpoint (Letta 0.16.8 only implements server-side
    embeddings for OpenAI-compatible backends)
  - Answer generation: gemini-2.5-flash, temperature 0 (same as the
    other vendor adapters)
  - Retrieval: `passages.search(query=question, top_k=25)`; evidence_ids
    = first-seen order of episode_id tags over ranked passages

Usage:
  python bench/adapters/letta_archival.py <episodes.json> <qa.json> <out-answers.json> \
      [--k 5] [--data-dir .letta-bench] [--base-url http://localhost:8283] \
      [--search-limit 25] [--ingest-workers 8] [--answer-workers 8]

Requires: GEMINI_API_KEY, a running Letta server with a google_ai
provider registered. `pip install letta-client google-genai`.
Ingest and answering both checkpoint; rerunning resumes.
"""

import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

LLM_MODEL = "gemini-2.5-flash"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
AGENT_MODEL = "google_ai/gemini-2.5-flash"
# Letta 0.16.8 implements server-side embeddings only for OpenAI-compatible
# backends, so the embedder is gemini-embedding-001 spoken over Google's
# OpenAI-compatible endpoint (OPENAI_API_KEY must be set to the Gemini key).
AGENT_EMBEDDING_CONFIG = {
    "embedding_endpoint_type": "openai",
    "embedding_endpoint": "https://generativelanguage.googleapis.com/v1beta/openai",
    "embedding_model": "gemini-embedding-001",
    "embedding_dim": 3072,
    "embedding_chunk_size": 1000,
}
SYSTEM_NAME = "letta-archival"
EPISODE_ID_RE = re.compile(r"Decision episode (\S+) —")


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
    # Deterministic synthetic timeline: month 1 → 2018-01-01 (same across adapters).
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
            tag = f" [episode_id: {m['episode_id']}]" if m.get("episode_id") else ""
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("episodes")
    ap.add_argument("qa")
    ap.add_argument("out")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--llm", choices=["gemini", "anthropic"], default="gemini", help="model family that CREATES (extraction where applicable + answers)")
    ap.add_argument("--data-dir", default=".letta-bench")
    ap.add_argument("--base-url", default=os.environ.get("LETTA_BASE_URL", "http://localhost:8283"))
    ap.add_argument("--search-limit", type=int, default=25)
    ap.add_argument("--ingest-workers", type=int, default=8)
    ap.add_argument("--answer-workers", type=int, default=8)
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY is required (embeddings)")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if args.llm == "anthropic" and not anthropic_key:
        sys.exit("ANTHROPIC_API_KEY is required with --llm anthropic")
    create_key = anthropic_key if args.llm == "anthropic" else api_key

    from letta_client import Letta

    client = Letta(base_url=args.base_url)
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    # One agent holds the firm-wide decision log (cross-household tasks need one store).
    agent_path = data_dir / "agent.json"
    if agent_path.exists():
        agent_id = json.loads(agent_path.read_text())["agent_id"]
    else:
        agent = client.agents.create(
            name="decisionsynth-bench",
            model=AGENT_MODEL,
            embedding_config=AGENT_EMBEDDING_CONFIG,
            memory_blocks=[
                {"label": "persona", "value": "Archival store for a financial-advisory decision log."},
            ],
        )
        agent_id = agent.id
        agent_path.write_text(json.dumps({"agent_id": agent_id}))
    print(f"[letta] agent {agent_id}", flush=True)

    episodes = json.loads(Path(args.episodes).read_text())["episodes"]
    tasks = json.loads(Path(args.qa).read_text())["qa_tasks"]

    # ── ingest (checkpointed) ──
    done_path = data_dir / "ingested.json"
    done = set(json.loads(done_path.read_text())) if done_path.exists() else set()
    todo = [e for e in episodes if e["episode_id"] not in done]
    print(f"[letta] ingest: {len(done)} done, {len(todo)} to go", flush=True)
    lock = threading.Lock()

    def ingest_one(e: dict) -> str:
        for attempt in range(6):
            try:
                client.agents.passages.create(
                    agent_id,
                    text=render_episode(e),
                    tags=[e["episode_id"]],
                    created_at=month_to_datetime(e["month_index"]),
                )
                return e["episode_id"]
            except Exception:  # noqa: BLE001 — retry transient API errors
                if attempt == 5:
                    raise
                time.sleep(min(2 ** attempt * 2, 60))
        return e["episode_id"]

    if todo:
        with ThreadPoolExecutor(max_workers=args.ingest_workers) as pool:
            futures = {pool.submit(ingest_one, e): e for e in todo}
            for n, fut in enumerate(as_completed(futures), 1):
                eid = fut.result()
                with lock:
                    done.add(eid)
                    if n % 50 == 0 or n == len(todo):
                        done_path.write_text(json.dumps(sorted(done)))
                        print(f"[letta] ingested {len(done)}/{len(episodes)}", flush=True)
        done_path.write_text(json.dumps(sorted(done)))

    # ── answer (checkpointed) ──
    partial_path = data_dir / f"answers-partial-{args.llm}-{Path(args.qa).stem}.json"
    answers = json.loads(partial_path.read_text()) if partial_path.exists() else {}
    todo_tasks = [t for t in tasks if t["task_id"] not in answers]
    print(f"[letta] answering: {len(answers)} done, {len(todo_tasks)} to go", flush=True)
    generate = make_answer_fn(args.llm, create_key)

    def passage_episode_id(p) -> str | None:
        tags = getattr(p, "tags", None) or []
        for t in tags:
            if EPISODE_ID_RE.match(f"Decision episode {t} —"):
                return t
        m = EPISODE_ID_RE.search(getattr(p, "content", "") or "")
        return m.group(1) if m else None

    def answer_one(task: dict) -> tuple:
        clean = {"task_id": task["task_id"], "task_type": task["task_type"], "question": task["question"]}
        res = None
        for attempt in range(6):
            try:
                res = client.agents.passages.search(agent_id, query=clean["question"], top_k=args.search_limit)
                break
            except Exception:  # noqa: BLE001 — retry transient API errors
                if attempt == 5:
                    raise
                time.sleep(min(2 ** attempt * 2, 60))
        hits = getattr(res, "results", None) or []
        evidence, seen, mems = [], set(), []
        for h in hits:
            eid = passage_episode_id(h)
            if eid and eid not in seen:
                seen.add(eid)
                evidence.append(eid)
            mems.append({"episode_id": eid, "text": getattr(h, "content", "") or ""})
        answer_key = generate(clean, mems)
        return clean["task_id"], {"task_id": clean["task_id"], "evidence_ids": evidence, "answer_key": answer_key, "_context": mems}

    if todo_tasks:
        with ThreadPoolExecutor(max_workers=args.answer_workers) as pool:
            futures = {pool.submit(answer_one, t): t for t in todo_tasks}
            for n, fut in enumerate(as_completed(futures), 1):
                try:
                    tid, ans = fut.result()
                except Exception as exc:  # noqa: BLE001 — skip failed task, keep the run alive
                    print(f"[letta] task failed ({futures[fut]['task_id']}): {exc}", flush=True)
                    continue
                with lock:
                    answers[tid] = ans
                    if n % 50 == 0 or n == len(todo_tasks):
                        partial_path.write_text(json.dumps(answers))
                        print(f"[letta] answered {len(answers)}/{len(tasks)}", flush=True)

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
    print(f"[letta] {SYSTEM_NAME}: answered {len(ordered)} tasks over {len(episodes)} episodes → {out}", flush=True)


if __name__ == "__main__":
    main()
