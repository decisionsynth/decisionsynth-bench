# Adapters

An adapter implements the `MemoryAdapter` contract in `../types.ts`: ingest
the episode corpus once, then answer each QA task with retrieved
`evidence_ids` and a typed `answer_key`. Adapters never see ground truth —
the runner strips answer keys, evidence ids, and distractors before a task
reaches `answer()`.

## In this repo

- `naive-baseline.ts` — deterministic lexical baseline. Stores episodes
  verbatim, retrieves by token overlap, answers by field extraction. Zero
  network, zero API keys. This is the *ceiling reference*: production memory
  systems compress, so the gap between a system's row and this row is what
  its pipeline lost.

## Vendor adapters (maintainer-run scoreboard rows)

- `mem0_oss.py` — Mem0 OSS (`Memory`, `infer=True` fact extraction), FAISS
  local vector store.
- `zep_graphiti.py` — Graphiti temporal knowledge graph (the OSS engine
  behind Zep), requires a Neo4j instance.
- `letta_archival.py` — self-hosted Letta server, archival-passage memory.

All three are Python (`pip install -r requirements.txt`, exact pins used for
the published rows) and require `GEMINI_API_KEY` — every vendor runs on the
same LLM/embedding stack (gemini-2.5-flash + gemini-embedding-001) to
isolate the memory pipeline, per the configuration note in `../SCOREBOARD.md`.
Each adapter renders episodes into identical plain-text decision memos,
ingests them through the vendor's own pipeline, retrieves 25 items in the
vendor's native unit per task, and generates typed answers from retrieved
memory content only. They emit the same `{system, answers}` JSON the scorer
consumes, so `bench/score.ts` remains the single scoring path. None of this
is part of the zero-key quickstart.

## Contributing an adapter

PRs welcome — vendor-neutral rules:

1. One file per system under `bench/adapters/`, self-contained apart from
   the vendor's own SDK.
2. No ground truth may reach the adapter (the runner enforces this; don't
   work around it).
3. Include the exact configuration (model names, index settings) needed to
   reproduce your run; scoreboard rows are only published from maintainer
   reruns on the private held-out set.
4. Fairness disputes are welcome — open an issue with your reproduction.
