/**
 * DecisionSynth Bench — adapter contract and scoring types.
 *
 * Self-contained: no imports beyond the Node standard library anywhere in
 * bench/. A memory system under evaluation implements `MemoryAdapter`:
 * ingest the episode corpus once, then answer each QA task. The scorer
 * (score.ts) compares SystemAnswer records against the ground-truth keys.
 */

/** A decision episode as published in data/episodes.json. The harness treats
 *  episodes as opaque JSON apart from the fields listed here. */
export interface EpisodeRecord {
  episode_id: string;
  month_index: number;
  decision_type: string;
  household_ref: { archetype_id: string; seed: number };
  trigger: {
    kind: string;
    event_type?: string;
    evidence: Record<string, unknown>;
  };
  semantic_refs: string[];
  procedural_path: {
    policy: string;
    recommended_option: string;
    [k: string]: unknown;
  };
  resolution: {
    followed_policy: boolean;
    override_reason?: string;
    outcome: string;
    outcome_status: string;
    [k: string]: unknown;
  };
  lineage?: string[];
  [k: string]: unknown;
}

export type QaTaskType =
  | "direct_recall"
  | "rationale_lookup"
  | "precedent_search"
  | "temporal_ordering"
  | "rule_attribution";

export interface QaTask {
  task_id: string;
  task_type: QaTaskType;
  question: string;
  /** Present in the dev set; withheld in the held-out set. */
  answer_key?: Record<string, unknown>;
  evidence_ids?: string[];
  distractor_ids?: string[];
}

/** What a system under evaluation must return per task. */
export interface SystemAnswer {
  task_id: string;
  /** Episode ids the system retrieved as evidence, best-first. */
  evidence_ids: string[];
  /** Typed answer in the same shape as the task type's answer key. */
  answer_key: Record<string, unknown>;
}

export interface MemoryAdapter {
  name: string;
  /** Called once with the full corpus before any questions. */
  ingest(episodes: EpisodeRecord[]): Promise<void> | void;
  /** Answer one task. The task's answer_key/evidence_ids are ground truth
   *  and are NEVER passed to the adapter — run-baseline.ts strips them. */
  answer(task: Omit<QaTask, "answer_key" | "evidence_ids" | "distractor_ids">): Promise<SystemAnswer> | SystemAnswer;
}

export interface TaskScore {
  task_id: string;
  task_type: QaTaskType;
  retrieval_precision_at_k: number;
  retrieval_recall_at_k: number;
  answer_exact_match: boolean;
}

export interface Scoreboard {
  system: string;
  k: number;
  task_count: number;
  by_type: Record<
    string,
    { tasks: number; precision_at_k: number; recall_at_k: number; exact_match_rate: number }
  >;
  overall: { precision_at_k: number; recall_at_k: number; exact_match_rate: number };
}
