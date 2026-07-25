#!/usr/bin/env python3
"""
DecisionSynth Bench — cross-provider answer validation.

The create/validate pattern: whichever model family generated a system's
answers, the OTHER family audits them. The validator sees exactly what
the creator saw — the question and the retrieved memory content (the
`.contexts.json` file the adapters dump alongside answers) — plus the
proposed answer, and judges whether the answer is supported by that
content. It never sees ground truth, and it does not change answers;
its output is a disagreement report published alongside the scoreboard
row (`validator_disagreement_rate`).

Usage:
  python bench/validate.py <answers.json> --validator {gemini,anthropic} \
      [--contexts <answers.json>.contexts.json] [--out report.json] [--workers 8]

Requires GEMINI_API_KEY or ANTHROPIC_API_KEY per --validator.
Models: gemini-2.5-flash (thinking off) / claude-haiku-4-5-20251001, temp 0.
"""

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

GEMINI_MODEL = "gemini-2.5-flash"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

VERDICT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "supported": {"type": "BOOLEAN"},
        "reason": {"type": "STRING"},
    },
    "required": ["supported", "reason"],
}

PROMPT = """You are auditing an answer produced by another AI system from retrieved memory content.

Question: {question}

Retrieved memory content the answering system saw:
{context}

The system's proposed answer (JSON):
{answer}

Judge ONLY whether the proposed answer is supported by the retrieved memory content above —
i.e., a careful reader of that content would produce the same answer values. Judge support,
not real-world truth; you have no access to the underlying records.

The proposed answer may contain "no answer" values for fields the system could not determine —
null, an empty list, or placeholder text such as "unknown" or "NOT_FOUND". Treat a "no answer"
value as SUPPORTED whenever the retrieved content above genuinely does not contain that specific
piece of information: a careful reader given only this content would reach the same "not found"
conclusion, so reporting it honestly is a pass, not a failure. Reserve UNSUPPORTED for a field
where the system instead filled in a concrete, specific value — a name, amount, status,
identifier, etc. — that the retrieved content does not state or contradicts. That is the guessing
case this check exists to catch.

If the answer mixes both — some fields correctly grounded or honestly left as "no answer", and
one concrete value not backed by the content — mark the whole answer unsupported and name the
offending field in "reason".

Reply with JSON:
{{"supported": true/false, "reason": "<one short sentence>"}}"""


def build_validator(provider: str):
    if provider == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

        def judge(prompt: str) -> dict:
            msg = client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=300,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
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

    else:
        from google import genai
        from google.genai import types as gtypes

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

        def judge(prompt: str) -> dict:
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=gtypes.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=VERDICT_SCHEMA,
                    thinking_config=gtypes.ThinkingConfig(thinking_budget=0),
                ),
            )
            if resp.text is None:
                raise ValueError("empty model response")
            return json.loads(resp.text)

    return judge


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("answers")
    ap.add_argument("--validator", choices=["gemini", "anthropic"], required=True)
    ap.add_argument("--qa", help="qa.json (for questions/task types); defaults to data/qa.json next to cwd")
    ap.add_argument("--contexts", help="contexts file; defaults to <answers>.contexts.json")
    ap.add_argument("--out")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    answers_file = json.loads(Path(args.answers).read_text())
    answers = answers_file["answers"]
    contexts = json.loads(Path(args.contexts or args.answers + ".contexts.json").read_text())
    qa_path = args.qa or "data/qa.json"
    task_meta = {
        t["task_id"]: {"question": t["question"], "task_type": t["task_type"]}
        for t in json.loads(Path(qa_path).read_text())["qa_tasks"]
    }
    judge = build_validator(args.validator)

    results: dict = {}
    lock = threading.Lock()

    def check(a: dict) -> tuple:
        meta = task_meta[a["task_id"]]
        ctx = contexts.get(a["task_id"], [])
        ctx_lines = []
        for i, m in enumerate(ctx, 1):
            eids = m.get("episode_ids") or ([m["episode_id"]] if m.get("episode_id") else [])
            tag = f" [episode_ids: {', '.join(eids)}]" if eids else ""
            ctx_lines.append(f"{i}.{tag} {m['text']}")
        prompt = PROMPT.format(
            question=meta["question"],
            context="\n".join(ctx_lines) or "(none retrieved)",
            answer=json.dumps(a["answer_key"]),
        )
        for attempt in range(6):
            try:
                v = judge(prompt)
                return a["task_id"], {"task_type": meta["task_type"], **v}
            except Exception:  # noqa: BLE001 — retry transient API errors
                if attempt == 5:
                    raise
                time.sleep(min(2 ** attempt * 2, 60))
        return a["task_id"], {"task_type": meta["task_type"], "supported": False, "reason": "validator error"}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(check, a): a for a in answers}
        for n, fut in enumerate(as_completed(futures), 1):
            try:
                tid, verdict = fut.result()
            except Exception as exc:  # noqa: BLE001 — skip failed task, keep the run alive
                print(f"[validate] task failed ({futures[fut]['task_id']}): {exc}", flush=True)
                continue
            with lock:
                results[tid] = verdict
                if n % 100 == 0 or n == len(answers):
                    print(f"[validate] {n}/{len(answers)}", flush=True)

    by_type: dict = {}
    for tid, v in results.items():
        g = by_type.setdefault(v["task_type"], {"tasks": 0, "unsupported": 0})
        g["tasks"] += 1
        if not v.get("supported"):
            g["unsupported"] += 1
    r3 = lambda n: round(n, 3)  # noqa: E731
    report = {
        "system": answers_file["system"],
        "validator": args.validator + "/" + (ANTHROPIC_MODEL if args.validator == "anthropic" else GEMINI_MODEL),
        "task_count": len(results),
        "disagreement_rate": r3(sum(1 for v in results.values() if not v.get("supported")) / max(len(results), 1)),
        "by_type": {
            t: {**g, "disagreement_rate": r3(g["unsupported"] / g["tasks"])} for t, g in sorted(by_type.items())
        },
        "disagreements": sorted(
            [{"task_id": tid, "reason": v.get("reason", "")} for tid, v in results.items() if not v.get("supported")],
            key=lambda d: d["task_id"],
        ),
    }
    out_text = json.dumps(report, indent=2) + "\n"
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(out_text)
    summary = {k: report[k] for k in ("system", "validator", "task_count", "disagreement_rate")}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
