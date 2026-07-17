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

## Planned (maintainer-run vendor rows)

Adapters for **Mem0 OSS**, **Zep / Graphiti**, and **Letta** are planned as
the first vendor scoreboard rows. Each requires that vendor's service and/or
an LLM + embedding key, so they are configured via environment variables and
are never part of the zero-key quickstart path.

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
