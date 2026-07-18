# Contributing

Thanks for wanting to make the benchmark better. Three contribution paths, in
order of how much we want them:

## 1. Dispute a score (yes, really)

Fairness disputes are engagement, not attacks. If you believe a scoreboard row
misrepresents a system — wrong configuration, unfair prompt rendering, a
retrieval budget that penalizes an architecture — open a
**benchmark fairness dispute** issue (template provided). The bar for
reopening a run: name the specific configuration you dispute (every row's
exact setup is in `bench/SCOREBOARD.md` and the adapter headers) and what you
would change. The harness is open and every run reproduces from a fresh
clone, so disputes are resolvable by rerunning, not by arguing.

## 2. Submit an adapter

Adapters implement the `MemoryAdapter` contract in `bench/types.ts` — ingest
`episodes.json`, answer each QA task with retrieved `evidence_ids` and a
typed `answer_key`. **Read [`bench/adapters/README.md`](bench/adapters/README.md)
first** — it is the contract of record: identical memo rendering across
vendors, the shared model stack, the 25-item retrieval budget, and the rule
that adapters never see ground truth. Submissions that change what the
adapter is allowed to see will be asked to rework before review.

Include with your PR:
- The adapter file (Python or TypeScript), configuration documented in its header
- Dependency pins (extend `bench/adapters/requirements.txt` if Python)
- A dev-set run: your `out/scoreboard.json` and the exact commands to reproduce it

Maintainers rerun submitted adapters before any scoreboard row is published —
self-reported numbers are never published directly.

## 3. Report a bug

Harness bugs, schema issues, scoring disagreements with the documented
semantics (`METHODOLOGY.md` §3 — read it before judging an episode "wrong"):
use the bug template.

## What we don't take

- New episodes or hand-written QA tasks. The corpus is generated
  deterministically upstream; answer keys are emitted by the generator, and
  hand-authored data would break exactly the property the benchmark sells.
- Changes to published scoreboard rows without a rerun.

## Licenses

Harness and schema contributions land under Apache-2.0; the dev-set data is
CC BY 4.0 and generated upstream (not editable here).
