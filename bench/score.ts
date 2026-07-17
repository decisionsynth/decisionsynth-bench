/**
 * DecisionSynth Bench — scorer.
 *
 * Usage:
 *   npx tsx bench/score.ts <qa.json> <system-answers.json> [--k 5] [--out scoreboard.json]
 *
 * Two axes per task:
 *  - Evidence retrieval: precision/recall@k of the system's evidence_ids
 *    against the ground-truth evidence_ids.
 *  - Answer correctness: typed exact match per task type —
 *      precedent_search  → unordered set match on episode entries
 *      temporal_ordering → ordered list match on episode_ids
 *      rule_attribution  → unordered set match on semantic_refs
 *      direct_recall / rationale_lookup → field-wise strict equality
 *
 * Deterministic, no dependencies. The same file scores the private held-out
 * set (where the maintainers hold the answer keys).
 */

import fs from "fs";
import path from "path";
import type { QaTask, SystemAnswer, TaskScore, Scoreboard, QaTaskType } from "./types";

function setEqual(a: unknown[], b: unknown[]): boolean {
  const key = (v: unknown) => JSON.stringify(v, Object.keys((v as object) ?? {}).sort());
  const sa = new Set(a.map(key));
  const sb = new Set(b.map(key));
  return sa.size === sb.size && [...sa].every((k) => sb.has(k));
}

function listEqual(a: unknown[], b: unknown[]): boolean {
  return a.length === b.length && a.every((v, i) => JSON.stringify(v) === JSON.stringify(b[i]));
}

export function answerMatches(
  taskType: QaTaskType,
  truth: Record<string, unknown>,
  system: Record<string, unknown>,
): boolean {
  switch (taskType) {
    case "precedent_search":
      return (
        Array.isArray(truth.episodes) &&
        Array.isArray(system.episodes) &&
        setEqual(truth.episodes, system.episodes)
      );
    case "temporal_ordering":
      return (
        Array.isArray(truth.episode_ids) &&
        Array.isArray(system.episode_ids) &&
        listEqual(truth.episode_ids, system.episode_ids)
      );
    case "rule_attribution":
      return (
        Array.isArray(truth.semantic_refs) &&
        Array.isArray(system.semantic_refs) &&
        setEqual(truth.semantic_refs, system.semantic_refs)
      );
    default: {
      // Field-wise strict equality on every ground-truth field.
      return Object.entries(truth).every(
        ([k, v]) => JSON.stringify(system[k]) === JSON.stringify(v),
      );
    }
  }
}

export function scoreTask(task: QaTask, answer: SystemAnswer, k: number): TaskScore {
  const truthEvidence = new Set(task.evidence_ids ?? []);
  const retrieved = answer.evidence_ids.slice(0, k);
  const hits = retrieved.filter((id) => truthEvidence.has(id)).length;
  return {
    task_id: task.task_id,
    task_type: task.task_type,
    retrieval_precision_at_k: retrieved.length > 0 ? hits / retrieved.length : 0,
    retrieval_recall_at_k: truthEvidence.size > 0 ? hits / truthEvidence.size : 0,
    answer_exact_match: answerMatches(task.task_type, task.answer_key ?? {}, answer.answer_key),
  };
}

export function buildScoreboard(system: string, scores: TaskScore[], k: number): Scoreboard {
  const byType: Scoreboard["by_type"] = {};
  const groups = new Map<string, TaskScore[]>();
  for (const s of scores) {
    const g = groups.get(s.task_type) ?? [];
    g.push(s);
    groups.set(s.task_type, g);
  }
  const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);
  const r3 = (n: number) => Math.round(n * 1000) / 1000;
  for (const [type, g] of [...groups.entries()].sort()) {
    byType[type] = {
      tasks: g.length,
      precision_at_k: r3(mean(g.map((s) => s.retrieval_precision_at_k))),
      recall_at_k: r3(mean(g.map((s) => s.retrieval_recall_at_k))),
      exact_match_rate: r3(mean(g.map((s) => (s.answer_exact_match ? 1 : 0)))),
    };
  }
  return {
    system,
    k,
    task_count: scores.length,
    by_type: byType,
    overall: {
      precision_at_k: r3(mean(scores.map((s) => s.retrieval_precision_at_k))),
      recall_at_k: r3(mean(scores.map((s) => s.retrieval_recall_at_k))),
      exact_match_rate: r3(mean(scores.map((s) => (s.answer_exact_match ? 1 : 0)))),
    },
  };
}

// ── CLI ────────────────────────────────────────────────────────────────────
if (require.main === module) {
  const args = process.argv.slice(2);
  const [qaPath, answersPath] = args;
  if (!qaPath || !answersPath) {
    console.error("usage: score.ts <qa.json> <system-answers.json> [--k 5] [--out scoreboard.json]");
    process.exit(2);
  }
  const kIdx = args.indexOf("--k");
  const k = kIdx !== -1 ? Number(args[kIdx + 1]) : 5;
  const outIdx = args.indexOf("--out");

  const qa = JSON.parse(fs.readFileSync(qaPath, "utf-8")) as { qa_tasks: QaTask[] };
  const answersFile = JSON.parse(fs.readFileSync(answersPath, "utf-8")) as {
    system: string;
    answers: SystemAnswer[];
  };
  const byId = new Map(answersFile.answers.map((a) => [a.task_id, a]));

  const missing: string[] = [];
  const scores: TaskScore[] = [];
  for (const task of qa.qa_tasks) {
    const answer = byId.get(task.task_id);
    if (!answer) {
      missing.push(task.task_id);
      scores.push({
        task_id: task.task_id,
        task_type: task.task_type,
        retrieval_precision_at_k: 0,
        retrieval_recall_at_k: 0,
        answer_exact_match: false,
      });
      continue;
    }
    scores.push(scoreTask(task, answer, k));
  }

  const board = buildScoreboard(answersFile.system, scores, k);
  if (missing.length > 0) {
    console.error(`⚠ ${missing.length} task(s) unanswered (scored as zero)`);
  }
  console.log(JSON.stringify(board, null, 2));
  if (outIdx !== -1) {
    fs.mkdirSync(path.dirname(path.resolve(args[outIdx + 1])), { recursive: true });
    fs.writeFileSync(args[outIdx + 1], JSON.stringify(board, null, 2) + "\n");
  }
}
