# DecisionSynth Bench

**Synthetic decision data for agent memory.** The first decision-relevant memory benchmark for financial services: can your memory system surface the *decisions* made about a client — not just chat transcripts — when an agent needs them?

[![Harness: Apache-2.0](https://img.shields.io/badge/harness-Apache--2.0-blue)](LICENSE)
[![Dev set: CC BY 4.0](https://img.shields.io/badge/dev%20set-CC%20BY%204.0-green)](data/)
[![Dev set](https://img.shields.io/badge/episodes-591%20dev%20%2B%20543%20held--out-8a2be2)](bench/SCOREBOARD.md)

**Held-out scoreboard** (private episode set, disjoint households, maintainer-run — [full scoreboard + configuration](bench/SCOREBOARD.md)):

| System (creator) | Overall EM | R@5 |
|---|---|---|
| naive-lexical-baseline (verbatim storage, ceiling ref) | **0.980** | 0.994 |
| letta-archival (gemini / claude) | 0.922 / 0.917 | 0.821 |
| mem0-oss (gemini / claude) | 0.465 / 0.136 | 0.439 / 0.781 |
| zep-graphiti (gemini / claude) | 0.215 / 0.091 | 0.719 / 0.475 |

The baseline stores everything verbatim and greps it — the gap between a vendor row and that row is **what the memory pipeline lost**. Both creator-model variants are published because the swing between them is itself a finding.

**Run it in two commands** (no API keys):

```bash
npm install && npm run baseline && npm run score
```

More: [Methodology](METHODOLOGY.md) · [Scoreboard](bench/SCOREBOARD.md) · [Buy the full corpus](https://www.wealthschema.com/decisionsynth?utm_source=github&utm_medium=referral&utm_campaign=decisionsynth-bench) · [Data sheet (PDF)](https://www.wealthschema.com/decisionsynth/data-sheet?utm_source=github&utm_medium=referral&utm_campaign=decisionsynth-bench) · [decisionsynth.com](https://decisionsynth.com)

## Why this exists

Existing memory benchmarks (LoCoMo, LongMemEval, BEAM) test passive conversational recall. Real agent memory failures are *decision-shaped*: "why did we take a 401(k) loan instead of a hardship withdrawal in March?", "which similar clients overrode this policy, and did it survive review?", "which regulatory figures governed that choice?". DecisionSynth Bench evaluates exactly that, over a corpus where every answer is **known by construction** — the deterministic generator that produced each episode also emitted its ground truth. No hand-authored answers, no LLM-generated labels.

## What's in the box

- `schema/decision-episode.schema.json` — the open episode + QA-task schema (Apache-2.0)
- `data/` — the dev set (CC BY 4.0): ~590 decision episodes over 71 synthetic household archetypes, with QA answer keys
- `bench/` — the evaluation harness: adapter contract, scoring script, and a deterministic lexical baseline that runs with **zero API keys**
- `METHODOLOGY.md` — how the corpus is built, what is calibrated vs. authored, and the semantics you need before judging an episode "wrong"

## Quickstart

```bash
# score the built-in lexical baseline on the dev set (no API keys required)
npm install
npm run baseline   # tsx bench/run-baseline.ts data/episodes.json data/qa.json out/baseline-answers.json
npm run score      # tsx bench/score.ts data/qa.json out/baseline-answers.json --out out/scoreboard.json
```

To evaluate your own memory system, implement the adapter contract in `bench/types.ts`: ingest `episodes.json`, then answer each task in `qa.json` with `evidence_ids` (what you retrieved) and an `answer_key` (typed, per task type). Score with `bench/score.ts`.

## Scoring

Two axes per task, aggregated per task type:

- **Evidence retrieval:** precision / recall @k over `evidence_ids`
- **Answer correctness:** typed exact match against the ground-truth key (unordered set match for `precedent_search`, ordered match for `temporal_ordering`, field-wise match elsewhere)

## The held-out scoreboard

The published dev set ships with its answer keys so you can develop freely. The public scoreboard is run by the maintainers on a **held-out episode set over disjoint households** whose episodes and answers are never published — plausible imitation of the free sample cannot produce verified ground truth against households it has never seen. Fairness disputes are welcome: the harness is open, runs are reproducible from a fresh clone, and there is no pay-to-play.

## Provenance & steward

Episodes are generated deterministically (seeded PRNG, versioned generators, Zod-gated; same seed → byte-identical output) from the WealthSynth synthetic-household substrate: SCF-calibrated households, 96-month trajectories, NCHS/SSA/BLS-calibrated life-event hazards, and regulatory figures cited to IRS/Treasury primary sources. Advisor *behavior* (override rates, outcome splits) is **authored, not calibrated** — disclosed in full in `METHODOLOGY.md`, and benchmark scores do not depend on it.

DecisionSynth Bench is stewarded by [WealthSchema](https://www.wealthschema.com/?utm_source=github&utm_medium=referral&utm_campaign=decisionsynth-bench), which sells the full corpus and custom decision batches. The benchmark itself is free, open, and vendor-neutral. The regulatory figures episodes cite via `semantic_refs` are served live (with primary-source citations) by the [WealthSchema Rule Sets feed](https://www.wealthschema.com/rule-sets?utm_source=github&utm_medium=referral&utm_campaign=decisionsynth-bench); a free synthetic-household sample is at [wealthschema.com/sample](https://www.wealthschema.com/sample?utm_source=github&utm_medium=referral&utm_campaign=decisionsynth-bench).

## Licenses

- Schema + harness: **Apache-2.0**
- Dev-set corpus (`data/`): **CC BY 4.0**
- Full corpus & held-out set: proprietary (see [wealthschema.com/datasets](https://www.wealthschema.com/datasets?utm_source=github&utm_medium=referral&utm_campaign=decisionsynth-bench))
