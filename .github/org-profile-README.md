<!--
  STAGED CONTENT — not rendered from this repo.
  Copy this file to the org-level profile repo:
    decisionsynth/.github  →  profile/README.md
  (Owner creates that repo; GitHub then renders it at github.com/decisionsynth.)
-->

# DecisionSynth

**Decision memory data for AI agents — with answer keys.**

Real agent-memory failures are decision-shaped: *why did we take the 401(k) loan instead of the
hardship withdrawal? which clients overrode this policy, and did it survive review?*
DecisionSynth generates deterministic advisor-decision episodes over synthetic households and
scores memory systems against ground truth the generator emitted itself — known-answer by
construction, never hand-labeled.

- **[decisionsynth-bench](https://github.com/decisionsynth/decisionsynth-bench)** — the open
  benchmark: free dev set (CC BY 4.0), open schema, scoring harness, no-API-key baseline, and a
  held-out scoreboard over households the dev set never saw.
- **[Commercial corpus](https://www.wealthschema.com/decisionsynth?utm_source=github&utm_medium=referral&utm_campaign=decisionsynth-bench)** —
  1,979 episodes / 4,913 QA tasks over 1,752 fresh households, disjoint from both benchmark sets.
- **[decisionsynth.com](https://decisionsynth.com)** — the one-page overview.

DecisionSynth is a product line of [WealthSchema](https://www.wealthschema.com/?utm_source=github&utm_medium=referral&utm_campaign=decisionsynth-bench),
which stewards the benchmark and sells the corpus. All data is synthetic — zero PII.
