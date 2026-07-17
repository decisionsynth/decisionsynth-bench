# DecisionSynth Bench — Scoreboard

**Dataset:** dev set `decisionsynth-sample-dev-0.1` (591 episodes, 1,487 tasks) · engine v0.2.1 · k=5.
Launch scoreboard entries below are maintainer-run. The public leaderboard is run on the **private held-out set**; dev-set numbers are for development reference.

## How to read this

The **naive lexical baseline stores every episode verbatim and greps it**. For a corpus this size that is a near-ceiling strategy — and that is the point of the benchmark: production agent-memory systems do *not* store verbatim; they extract, summarize, and graph. The measurement is **how much decision-relevant structure survives your system's compression**: the gap between your row and the baseline row is what your memory pipeline lost. Multi-episode tasks (`precedent_search`, `temporal_ordering`) additionally require aggregation no single retrieved record contains.

| System | Overall EM | P@5 | R@5 | recall EM | rationale EM | precedent EM | temporal EM | attribution EM |
|---|---|---|---|---|---|---|---|---|
| naive-lexical-baseline (verbatim storage, ceiling ref) | 0.950 | 0.292 | 0.972 | 0.946 | 0.964 | 1.000 | 0.907 | 0.964 |
| _Mem0 OSS_ | _pending_ | | | | | | | |
| _Zep / Graphiti_ | _pending_ | | | | | | | |
| _Letta_ | _pending_ | | | | | | | |

*EM = answer exact-match rate per §Scoring in the README. P@5 for single-evidence tasks is bounded at 0.2 by construction (1 relevant id, 5 returned).*

## Reproduce

```bash
npm install
npm run baseline   # → out/baseline-answers.json
npm run score      # → out/scoreboard.json
```

The committed reference run is `results/naive-lexical-baseline.dev.json`.
