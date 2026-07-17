#!/usr/bin/env python3
"""
DecisionSynth Bench — Mem0 OSS adapter (maintainer-run vendor row).

Pipeline under measurement: mem0's OSS memory layer (fact extraction +
memory-update LLM pipeline, vector retrieval). Each decision episode is
rendered as a plain-text decision memo and ingested with
`Memory.add(..., infer=True)` — mem0's own extraction decides what
survives. Tasks are answered from mem0 search results ONLY: the answer
LLM sees the retrieved memory texts (plus each memory's `episode_id`
metadata, a passthrough field mem0 stores verbatim) — never the raw
episode corpus.

Run configuration (published with the scoreboard row per adapters/README
rule 3):
  - mem0ai 2.0.12 (OSS `Memory`, infer=True, default prompts)
  - LLM: gemini-2.5-flash, temperature 0 (mem0 extraction/update AND
    answer generation)
  - Embedder: gemini-embedding-001, 768 dims (MRL truncation), FAISS
    (cosine) local vector store
  - Retrieval: `Memory.search(question, limit=25)`; evidence_ids =
    first-seen order of episode_id metadata over ranked results
  - Single shared user_id ("decisionsynth-corpus") so cross-household
    tasks (precedent_search) are answerable, mirroring a firm-wide
    decision log.

Usage:
  python bench/adapters/mem0_oss.py <episodes.json> <qa.json> <out-answers.json> \
      [--k 5] [--data-dir .mem0-bench] [--search-limit 25] [--ingest-workers 4] [--answer-workers 8]

Requires: GEMINI_API_KEY. `pip install mem0ai google-genai faiss-cpu`.
Ingest and answering both checkpoint; rerunning resumes.
"""

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

LLM_MODEL = "gemini-2.5-flash"
EMBED_MODEL = "models/gemini-embedding-001"
EMBED_DIMS = 768
USER_ID = "decisionsynth-corpus"
SYSTEM_NAME = "mem0-oss"

os.environ.setdefault("MEM0_TELEMETRY", "False")


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


def make_answer_fn(api_key: str):
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
    ap.add_argument("--data-dir", default=".mem0-bench")
    ap.add_argument("--search-limit", type=int, default=25)
    ap.add_argument("--ingest-workers", type=int, default=4)
    ap.add_argument("--answer-workers", type=int, default=8)
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY is required")

    from mem0 import Memory

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    memory = Memory.from_config(
        {
            "llm": {
                "provider": "gemini",
                "config": {"model": LLM_MODEL, "api_key": api_key, "temperature": 0.0, "max_tokens": 4096},
            },
            "embedder": {
                "provider": "gemini",
                "config": {"model": EMBED_MODEL, "api_key": api_key, "embedding_dims": EMBED_DIMS},
            },
            "vector_store": {
                "provider": "faiss",
                "config": {
                    "path": str(data_dir / "faiss"),
                    "embedding_model_dims": EMBED_DIMS,
                    "distance_strategy": "cosine",
                },
            },
            "history_db_path": str(data_dir / "history.db"),
        }
    )

    episodes = json.loads(Path(args.episodes).read_text())["episodes"]
    tasks = json.loads(Path(args.qa).read_text())["qa_tasks"]

    # ── ingest (checkpointed) ──
    done_path = data_dir / "ingested.json"
    done = set(json.loads(done_path.read_text())) if done_path.exists() else set()
    todo = [e for e in episodes if e["episode_id"] not in done]
    print(f"[mem0] ingest: {len(done)} done, {len(todo)} to go", flush=True)
    lock = threading.Lock()

    def ingest_one(e: dict) -> str:
        text = render_episode(e)
        for attempt in range(6):
            try:
                memory.add(
                    messages=[{"role": "user", "content": text}],
                    user_id=USER_ID,
                    metadata={"episode_id": e["episode_id"]},
                    infer=True,
                )
                return e["episode_id"]
            except Exception as exc:  # noqa: BLE001 — retry transient API errors
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
                    if n % 25 == 0 or n == len(todo):
                        done_path.write_text(json.dumps(sorted(done)))
                        print(f"[mem0] ingested {len(done)}/{len(episodes)}", flush=True)
        done_path.write_text(json.dumps(sorted(done)))

    # ── answer (checkpointed) ──
    partial_path = data_dir / f"answers-partial-{Path(args.qa).stem}.json"
    answers = json.loads(partial_path.read_text()) if partial_path.exists() else {}
    todo_tasks = [t for t in tasks if t["task_id"] not in answers]
    print(f"[mem0] answering: {len(answers)} done, {len(todo_tasks)} to go", flush=True)
    generate = make_answer_fn(api_key)

    def answer_one(task: dict) -> tuple:
        clean = {"task_id": task["task_id"], "task_type": task["task_type"], "question": task["question"]}
        res = None
        for attempt in range(6):
            try:
                res = memory.search(query=clean["question"], filters={"user_id": USER_ID}, limit=args.search_limit)
                break
            except Exception:  # noqa: BLE001 — retry transient API errors
                if attempt == 5:
                    raise
                time.sleep(min(2 ** attempt * 2, 60))
        hits = res.get("results", res) if isinstance(res, dict) else res
        evidence, seen, mems = [], set(), []
        for h in hits:
            eid = (h.get("metadata") or {}).get("episode_id")
            if eid and eid not in seen:
                seen.add(eid)
                evidence.append(eid)
            mems.append({"episode_id": eid, "text": h.get("memory", "")})
        answer_key = generate(clean, mems)
        return clean["task_id"], {"task_id": clean["task_id"], "evidence_ids": evidence, "answer_key": answer_key}

    if todo_tasks:
        with ThreadPoolExecutor(max_workers=args.answer_workers) as pool:
            futures = {pool.submit(answer_one, t): t for t in todo_tasks}
            for n, fut in enumerate(as_completed(futures), 1):
                try:
                    tid, ans = fut.result()
                except Exception as exc:  # noqa: BLE001 — skip failed task, keep the run alive
                    print(f"[mem0] task failed ({futures[fut]['task_id']}): {exc}", flush=True)
                    continue
                with lock:
                    answers[tid] = ans
                    if n % 50 == 0 or n == len(todo_tasks):
                        partial_path.write_text(json.dumps(answers))
                        print(f"[mem0] answered {len(answers)}/{len(tasks)}", flush=True)

    ordered = [answers[t["task_id"]] for t in tasks if t["task_id"] in answers]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"system": SYSTEM_NAME, "answers": ordered}, indent=2) + "\n")
    print(f"[mem0] {SYSTEM_NAME}: answered {len(ordered)} tasks over {len(episodes)} episodes → {out}", flush=True)


if __name__ == "__main__":
    main()
