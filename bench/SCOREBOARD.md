# DecisionSynth Bench — Scoreboard

**Dataset:** dev set `decisionsynth-sample-dev-0.1` (591 episodes, 1,487 tasks) · engine v0.2.1 · k=5.
Launch scoreboard entries below are maintainer-run. The public leaderboard is run on the **private held-out set** (see [Held-out scoreboard](#held-out-scoreboard--launch-2026-07-18)); dev-set numbers are for development reference.

## How to read this

The **naive lexical baseline stores every episode verbatim and greps it**. For a corpus this size that is a near-ceiling strategy — and that is the point of the benchmark: production agent-memory systems do *not* store verbatim; they extract, summarize, and graph. The measurement is **how much decision-relevant structure survives your system's compression**: the gap between your row and the baseline row is what your memory pipeline lost. Multi-episode tasks (`precedent_search`, `temporal_ordering`) additionally require aggregation no single retrieved record contains.

| System | Overall EM | P@5 | R@5 | recall EM | rationale EM | precedent EM | temporal EM | attribution EM |
|---|---|---|---|---|---|---|---|---|
| naive-lexical-baseline (verbatim storage, ceiling ref) | 0.950 | 0.292 | 0.972 | 0.946 | 0.964 | 1.000 | 0.907 | 0.964 |
| letta-archival (archival passages, verbatim) | 0.892 | 0.169 | 0.765 | 0.917 | 0.813 | 0.727 | 0.747 | 0.931 |
| mem0-oss (fact extraction, `infer=True`) | 0.321 | 0.080 | 0.366 | 0.291 | 0.402 | 0.364 | 0.401 | 0.311 |
| zep-graphiti (temporal knowledge graph) | 0.128 | 0.162 | 0.737 | 0.036 | 0.009 | 0.000 | 0.786 | 0.044 |

*EM = answer exact-match rate per §Scoring in the README. P@5 for single-evidence tasks is bounded at 0.2 by construction (1 relevant id, 5 returned).*

**Vendor-row configuration (maintainer runs, 2026-07-17).** All vendor adapters run on the same model stack to isolate the memory pipeline: extraction/agent LLM and answer generation `gemini-2.5-flash` (temperature 0, thinking disabled for answer extraction), embeddings `gemini-embedding-001`. Episodes are rendered as identical plain-text decision memos across vendors; answers are generated from each vendor's retrieved memory content only (plus per-memory episode-id provenance the vendor stores natively — mem0 metadata, Letta tags, Graphiti episodic provenance). Exact per-vendor configuration is in each adapter's header (`bench/adapters/*.py`); dependency pins in `bench/adapters/requirements.txt`.

## Cross-provider create/validate (2026-07-18)

Vendor pipelines embed an LLM, so a scoreboard row is really *pipeline × extraction model*. Each configuration therefore runs twice — once with Gemini (`gemini-2.5-flash`) and once with Anthropic Claude (`claude-haiku-4-5`) as the creating model (vendor extraction where applicable + answer generation; embeddings are `gemini-embedding-001` in all rows) — and each family's answers are audited by the **other** family against the same retrieved context (`bench/validate.py`; the validator never sees ground truth). Dev set, k=5:

| System (creator) | Overall EM | R@5 | Cross-validator disagreement |
|---|---|---|---|
| letta-archival (gemini) | 0.892 | 0.765 | 0.165 (claude) |
| letta-archival (claude) | 0.884 | 0.765 | 0.130 (gemini) |
| mem0-oss (gemini) | 0.321 | 0.366 | 0.452 (claude) |
| mem0-oss (claude) | 0.293 | 0.582 | 0.553 (gemini) |
| zep-graphiti (gemini) | 0.128 | 0.737 | 0.578 (claude) |
| zep-graphiti (claude) | 0.069 | 0.425 | 0.895 (gemini) |

Three findings the two-creator design surfaces:

1. **Verbatim storage is creator-invariant; extraction is not.** Letta's rows barely move across creators (EM 0.892 vs 0.884) because nothing is extracted. The extraction pipelines swing hard — and in *opposite directions per architecture*.
2. **The same model family loses different things in different pipelines.** Under mem0, Claude extraction preserves episode identity far better (R@5 0.582 vs 0.366) but discards field detail — dotted reference citations vanish entirely (attribution EM 0.000; the retrieved memories contain no `semantic_refs` strings at all). Under Graphiti, Claude-haiku extracts ~2.8 edge facts per episode where gemini-flash extracts ~18, starving the graph (R@5 0.425 vs 0.737; temporal EM 0.198 vs 0.786).
3. **The cross-validator tracks answer quality without ever seeing ground truth.** Disagreement rates order the rows the same way EM does (letta ≈ 0.13–0.17, mem0 ≈ 0.45–0.55, graphiti-claude 0.90), so `validate.py` is usable as an unsupervised health signal on corpora where answer keys are withheld.

Full validation reports (per-task disagreement reasons) accompany the maintainer archives.

## Held-out scoreboard — launch (2026-07-18)

**Dataset:** the private held-out set — 543 episodes / 1,367 tasks over households **disjoint** from the dev set · engine v0.2.1 · k=5 · maintainer-run. Episodes and answer keys are never published (that is the benchmark's structural defense against imitation); the aggregate scoreboards behind every row are committed in `results/*.heldout.json`. Both creator variants are published side by side — the cross-provider findings above are the reason there is no single "primary" model.

| System (creator) | Overall EM | P@5 | R@5 | recall EM | rationale EM | precedent EM | temporal EM | attribution EM | Cross-validator disagreement |
|---|---|---|---|---|---|---|---|---|---|
| naive-lexical-baseline (deterministic, no LLM) | 0.980 | 0.302 | 0.994 | 0.978 | 0.971 | 1.000 | 0.982 | 0.982 | — |
| letta-archival (gemini) | 0.922 | 0.181 | 0.821 | 0.947 | 0.905 | 0.667 | 0.760 | 0.956 | 0.129 (claude) |
| letta-archival (claude) | 0.917 | 0.181 | 0.821 | 0.947 | 0.905 | 0.667 | 0.719 | 0.956 | 0.087 (gemini) |
| mem0-oss (gemini) | 0.465 | 0.095 | 0.439 | 0.527 | 0.038 | 0.333 | 0.521 | 0.470 | 0.386 (claude) |
| mem0-oss (claude) | 0.136 | 0.167 | 0.781 | 0.238 | 0.010 | 0.222 | 0.323 | 0.000 | 0.492 (gemini) |
| zep-graphiti (gemini) | 0.215 | 0.162 | 0.719 | 0.110 | 0.000 | 0.000 | 0.886 | 0.158 | 0.561 (claude) |
| zep-graphiti (claude) | 0.091 | 0.107 | 0.475 | 0.083 | 0.000 | 0.000 | 0.389 | 0.028 | 0.908 (gemini) |

Held-out reading notes:

- **The dev-set ordering holds on unseen households** — baseline > letta > mem0 > graphiti on overall EM, in both creator variants — so the dev set is a faithful development proxy.
- **Extraction quality varies corpus-to-corpus.** mem0 (gemini) rationale EM collapsed from 0.402 (dev) to 0.038 (held-out) while its overall EM *rose* (0.321 → 0.465): the same pipeline preserves different structure on different data. Single-corpus memory evals overfit their corpus.
- **zep-graphiti posts the best temporal_ordering of any LLM-backed system (0.886)** — above its own dev number and beating verbatim-storage letta (0.760) — while still losing exact identifiers to edge-fact granularity (recall EM 0.110). Same architecture, opposite extremes, one benchmark run.
- `precedent_search` has only 9 held-out tasks (rarest trigger type in the coverage frame) — treat that column as directional, not significant.
- Letta's two creator rows share identical retrieval (R@5 0.821 — same embeddings, verbatim passages); the small EM gap is answer generation alone. The cross-validator's lowest disagreement (0.087) lands on the same rows EM ranks highest — ground-truth-free validation continues to track quality on the corpus where answer keys are withheld.

**Reading the vendor rows:** letta-archival stores memos verbatim (its archival path does no extraction), so its row sits near the baseline ceiling and mostly measures retrieval quality (R@5 0.765 vs 0.972). mem0-oss runs its fact-extraction pipeline (`infer=True`), and the gap — overall EM 0.321 vs 0.950 — is decision-relevant structure the extraction discarded: exact outcome identifiers, full `semantic_refs` lists, and episode identity needed for multi-episode tasks. zep-graphiti is the most instructive split: its *episode-level* retrieval is strong (R@5 0.737) and it posts the **best temporal_ordering EM of any system (0.786** vs the baseline's 0.907) — the temporal graph doing exactly what it is designed for — but its retrieval unit is the individual *edge fact*, and one decision memo shreds into ~25 facts. At the matched retrieval budget (25 items) the anchor decision's outcome/status facts are usually crowded out, so exact-identifier answers fail (recall EM 0.036) even when the graph provably contains the fact. Some `outcome_status` edges were also dropped at extraction (entity-resolution failures during bulk ingest). Granularity of the retrieval unit — passages vs facts vs edges — is a first-order variable this benchmark surfaces; all rows use the same 25-item budget in each system's native unit.

## Reproduce

```bash
npm install
npm run baseline   # → out/baseline-answers.json
npm run score      # → out/scoreboard.json
```

The committed reference run is `results/naive-lexical-baseline.dev.json`.
