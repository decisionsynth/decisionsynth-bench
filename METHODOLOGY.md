# DecisionSynth — Methodology

**Versions described:** episodes `dsynth-0.1.0` · engine `DECISIONS_VERSION v0.2.1` · behavioral assumptions `BEHAVIOR_PARAMS_VERSION v0.1.0` · reference feed `us-federal 2026 (2026.1.0-preview)`.

---

## 1. What an episode is

A **decision episode** is a deterministic projection of a synthetic household's financial trajectory through a policy engine: a trigger (a scheduled life event whose numbers visibly move the household's 96-month trajectory), the options a firm would consider (with the cited regulatory figures that permit or block each), a policy recommendation, a seeded behavioral resolution (follow / override / escalate), and typed ground-truth QA tasks emitted at generation time.

**No LLM is involved anywhere in the generation path.** Every field derives from the household JSON, its trajectory, its life-event schedule, or a cited fact key. A field not derivable from those sources is treated as a generator bug, not a default.

## 2. Calibrated vs. authored — the honesty table

Two different kinds of numbers appear in this corpus. They are labeled per row and must never be conflated:

| Layer | Status | Source / rationale |
|---|---|---|
| Household demographics, finances | **Calibrated** | SCF-anchored samplers (see WealthSynth corpus documentation) |
| Life-event hazards (job loss, illness, disability, college, …) | **Calibrated** | NCHS, SSA, BLS, Census, Fed SCF wealth-transfer waves — cited in the generator source |
| Life-event financial impacts (income dips, expense deltas) | **Calibrated anchors** | BLS median unemployment duration + UI replacement; LTD/SSDI replacement ratios; documented in-code |
| Regulatory figures (contribution limits, brackets, penalties) | **Cited primary sources** | IRS/Treasury documents, per-fact citations in the Rule Sets feed |
| **Advisor behavior** (override rates, reason mix, outcome splits, client acceptance) | **AUTHORED** | Chosen for scenario diversity. There is no public benchmark for advisor override behavior; claiming calibration would be false. |

### Authored behavioral defaults (v0.1.0)

All values below are authored defaults, versioned in `behavior-params.ts`, stamped into every episode's `_meta.behavior_params_version`, and customer-overridable in custom generation (stamped `custom:<digest>`).

| Parameter | D1 emergency liquidity | D2 education funding | D3 retirement/Roth | Rationale |
|---|---|---|---|---|
| `p_override` | 0.25 | 0.15 | 0.20 | Liquidity crises produce the most policy tension; education is most rule-bound |
| Override-reason weights (enum order) | 40/25/20/15 | 35/30/20/15 | 35/30/20/15 | Economically-rational reason first |
| Outcome split (approve/deny/escalate) | 60/25/15 | 70/20/10 | 65/20/15 | Overrides usually survive review; escalation is the tail |
| `p_client_accepts_recommendation` | 0.85 | 0.90 | 0.80 | D3 is the most discretionary |
| Global | `emergency_floor_months` = 6 · `compliance_amount_threshold` = $50,000 · P(approved \| escalated) = 0.5 | | | |

**Sensitivity note:** benchmark scores do **not** depend on these values. DecisionSynth Bench tests whether a memory system can retrieve and attribute *recorded* episodes; it never asks a system to predict advisor behavior. Changing the authored parameters changes the corpus composition, not the correctness of any answer key.

**Observed vs. authored rates:** conditional reason eligibility (below) converts some override draws into follows, so observed marginal override rates sit slightly below `p_override` (dev set: ~15%). This is by design and disclosed rather than re-tuned.

## 3. Decision semantics (read this before judging an episode "wrong")

- **Options and permission.** Each episode lists the options a firm would consider with a `permitted` flag; a `blocking_refs` array cites the fact keys that rule an option out (e.g. job loss is not a §1.401(k)-1(d)(3) hardship safe-harbor reason; a plan loan cannot be originated after separation). The recommendation is the first permitted option in the type's policy order.
- **D3 bracket ceiling.** A partial Roth conversion is *recommended* only while ordinary taxable income sits below the top of the 24% bracket (from the cited bracket fact); above it, taxable investing ranks first and conversion remains permitted-but-not-recommended. Lump-sum proceeds (sales, inheritances) are treated as principal, not ordinary income — a v0 simplification, disclosed.
- **Waterfall funding (D1/D2).** Need-driven decisions fund the computed need across permitted options in policy order (the override target first when overridden). `outcome_params` carries `amount` (total funded), `need`, per-source `funded_<option>` tranches, and `funding_gap` when sources are genuinely exhausted. HSA reimbursements are capped at the triggering event's evidenced qualified medical cost.
- **Outcome status vocabulary.**
  - follow + `approved` — client accepted; the recommendation executed.
  - follow + `denied` — recommendation made per policy; client declined to act (auto-approve tier: no policy exception occurred).
  - override + `approved` / `escalated_then_approved` — the override option executed.
  - override + `denied` / `escalated_then_denied` — review enforced policy; `outcome` records the firm's resolved position (the recommended option). For client-driven override reasons, read this as the position of record, not a claim that money moved against the client's will.
- **Escalation.** Overrides whose total funded amount is ≥ $50,000 always escalate to compliance. Independently, the outcome split's escalate branch models *contentiousness*: supervisors punt disputed overrides at any amount, so small-amount compliance escalations appear (deliberately, owner-reviewed).
- **Conditional override reasons.** `avoid_selling_in_drawdown` requires a negative trailing 3-month portfolio return; `preserve_529_for_younger_sibling` requires a younger dependent; `niit_or_irmaa_interaction` requires the household to actually sit at/above the NIIT threshold; `liquidity_speed_over_penalty_cost` targets retirement-plan options only. A reason with no eligible target renormalizes out of the draw.

## 4. Provenance and replay

- Every episode stamps `_meta.domain_versions` (inherited from its household's stamped generator versions, plus `decisions`), `_meta.behavior_params_version`, and `_meta.reference_feed` (jurisdiction, tax year, feed version). `household_ref.domain_versions_digest` binds the episode to the exact generator versions that produced its substrate.
- Same `(archetype_id, seed, DECISIONS_VERSION, BEHAVIOR_PARAMS_VERSION)` → byte-identical episodes. Golden decision fixtures are pinned in CI; drift fails the build.
- Every candidate episode passes a Zod gate (schema + cross-field invariants + every cited fact key must resolve against the feed). Nothing invalid is written; the deterministic path has no retry — a gate failure is a bug.

## 5. QA tasks (benchmark ground truth)

Emitted at generation time — **known-answer by construction**; no answer is ever hand-authored or model-generated.

| Task type | Question shape | Answer key |
|---|---|---|
| `direct_recall` | What did household X decide at month t? | `outcome` + `outcome_status` |
| `rationale_lookup` | Why was policy overridden in episode E? | `override_reason` + trigger evidence |
| `precedent_search` | Which episodes overrode for reason R, with what outcomes? | episode-id set + statuses |
| `temporal_ordering` | What decisions preceded X's month-t decision within 24 months? | ordered episode-id list |
| `rule_attribution` | Which cited figures governed episode E? | `semantic_refs` (fact keys) |

Every task carries `evidence_ids` and ≥3 deterministic `distractor_ids` (same-household episodes preferred, then same decision type, month-proximity tie-break; distractors never overlap evidence). Scoring: evidence retrieval (precision/recall@k) + typed answer-key exact match.

## 6. Dev set vs. held-out test set

- **Dev set (public, CC BY 4.0):** ~590 episodes with full answer keys, over the first half of each archetype's canonical seed frame. Coverage rule: ≥2 episodes per archetype per observed decision type, measured and published in `coverage.json` (archetypes whose frame exhausted before a rare type drew a second episode are listed, not hidden).
- **Held-out test set (private):** ~540 episodes over the disjoint second half of the seed frame (zero household overlap, asserted at build time). Its episodes and answer keys are never published; the public scoreboard runs on it privately. This is the structural defense against LLM imitation of the free sample: an imitator can generate plausible-looking episodes, but cannot produce verified ground truth against households it has never seen.

## 7. Known v0 simplifications (disclosed)

- Applicability is seed-dependent: an archetype with no qualifying event at its sampled seeds contributes no episodes of that type (the coverage report says so).
- Lump-sum proceeds are treated as principal in the D3 bracket test; conversion sizing is `min(investable, traditional balance)`, not bracket-fill-optimized.
- Education-credit MAGI phaseouts use `single` keys for head-of-household (IRS-consistent) and married-filing-separately (approximation; MFS education-credit ineligibility is not modeled). The statutory MFS Roth phaseout band is omitted rather than mis-cited.
- Household ages advance from the projection window start (the scheduler's convention); snapshot ages are treated as window-start ages.
- Advisor behavior is authored (see §2) — this corpus is evaluation/seed data, not behavioral research.
