# DecisionSynth Bench — Scoreboard

**Dataset:** dev set `decisionsynth-sample-dev-0.1` (591 episodes, 1,487 tasks) · engine v0.2.1 · k=5.
Launch scoreboard entries below are maintainer-run. The public leaderboard is run on the **private held-out set**; dev-set numbers are for development reference.

## How to read this

The **naive lexical baseline stores every episode verbatim and greps it**. For a corpus this size that is a near-ceiling strategy — and that is the point of the benchmark: production agent-memory systems do *not* store verbatim; they extract, summarize, and graph. The measurement is **how much decision-relevant structure survives your system's compression**: the gap between your row and the baseline row is what your memory pipeline lost. Multi-episode tasks (`precedent_search`, `temporal_ordering`) additionally require aggregation no single retrieved record contains.

| System | Overall EM | P@5 | R@5 | recall EM | rationale EM | precedent EM | temporal EM | attribution EM |
|---|---|---|---|---|---|---|---|---|
| naive-lexical-baseline (verbatim storage, ceiling ref) | 0.950 | 0.292 | 0.972 | 0.946 | 0.964 | 1.000 | 0.907 | 0.964 |
| letta-archival (archival passages, verbatim) | 0.892 | 0.169 | 0.765 | 0.917 | 0.813 | 0.727 | 0.747 | 0.931 |
| mem0-oss (fact extraction, `infer=True`) | 0.321 | 0.080 | 0.366 | 0.291 | 0.402 | 0.364 | 0.401 | 0.311 |
| _Zep / Graphiti_ | _pending_ | | | | | | | |

*EM = answer exact-match rate per §Scoring in the README. P@5 for single-evidence tasks is bounded at 0.2 by construction (1 relevant id, 5 returned).*

**Vendor-row configuration (maintainer runs, 2026-07-17).** All vendor adapters run on the same model stack to isolate the memory pipeline: extraction/agent LLM and answer generation `gemini-2.5-flash` (temperature 0, thinking disabled for answer extraction), embeddings `gemini-embedding-001`. Episodes are rendered as identical plain-text decision memos across vendors; answers are generated from each vendor's retrieved memory content only (plus per-memory episode-id provenance the vendor stores natively — mem0 metadata, Letta tags, Graphiti episodic provenance). Exact per-vendor configuration is in each adapter's header (`bench/adapters/*.py`); dependency pins in `bench/adapters/requirements.txt`.

**Reading the first rows:** letta-archival stores memos verbatim (its archival path does no extraction), so its row sits near the baseline ceiling and mostly measures retrieval quality (R@5 0.765 vs 0.972). mem0-oss runs its fact-extraction pipeline (`infer=True`), and the gap — overall EM 0.321 vs 0.950 — is decision-relevant structure the extraction discarded: exact outcome identifiers, full `semantic_refs` lists, and episode identity needed for multi-episode tasks.

## Reproduce

```bash
npm install
npm run baseline   # → out/baseline-answers.json
npm run score      # → out/scoreboard.json
```

The committed reference run is `results/naive-lexical-baseline.dev.json`.
