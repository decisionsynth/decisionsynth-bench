/**
 * DecisionSynth Bench — naive lexical baseline.
 *
 * A deterministic, dependency-free reference adapter: token-overlap
 * retrieval over serialized episode facets, plus mechanical answer
 * extraction from the retrieved episodes. No LLM, no API keys, no network.
 *
 * Purpose: (a) prove the harness end-to-end from a fresh clone, and
 * (b) set the floor every real memory system should beat. It is honest but
 * simple — no embeddings, no graph, no temporal reasoning beyond what the
 * task type mechanically requires.
 */

import type { EpisodeRecord, MemoryAdapter, QaTask, SystemAnswer } from "../types";

const K = 5;

function tokenize(text: string): string[] {
  const raw = text
    .toLowerCase()
    .split(/[^a-z0-9\-_.]+/)
    .filter((t) => t.length > 1);
  // Also emit hyphen-split parts so "household A-01 (seed 1)" matches
  // tokens inside "d1-a-01-seed-1-m37".
  const out = new Set<string>(raw);
  for (const t of raw) for (const p of t.split("-")) if (p.length > 1) out.add(p);
  return [...out];
}

interface IndexedEpisode {
  episode: EpisodeRecord;
  tokens: Set<string>;
}

export class NaiveLexicalBaseline implements MemoryAdapter {
  name = "naive-lexical-baseline";
  private index: IndexedEpisode[] = [];
  private byId = new Map<string, EpisodeRecord>();
  private df = new Map<string, number>();

  ingest(episodes: EpisodeRecord[]): void {
    this.index = episodes.map((episode) => {
      const facets = [
        episode.episode_id,
        episode.household_ref.archetype_id,
        `seed-${episode.household_ref.seed}`,
        `seed ${episode.household_ref.seed}`,
        `m${episode.month_index}`,
        `month ${episode.month_index}`,
        episode.decision_type,
        episode.trigger.event_type ?? "",
        episode.resolution.override_reason ?? "",
        episode.resolution.outcome,
        episode.resolution.outcome_status,
        episode.procedural_path.recommended_option,
        ...episode.semantic_refs,
      ].join(" ");
      return { episode, tokens: new Set(tokenize(facets)) };
    });
    this.byId = new Map(episodes.map((e) => [e.episode_id, e]));
    this.df.clear();
    for (const ix of this.index) {
      for (const t of ix.tokens) this.df.set(t, (this.df.get(t) ?? 0) + 1);
    }
  }

  private retrieve(question: string): EpisodeRecord[] {
    const qTokens = tokenize(question);
    const scored = this.index.map((ix) => {
      let score = 0;
      for (const t of qTokens) {
        if (ix.tokens.has(t)) score += 1 / (1 + Math.log(1 + (this.df.get(t) ?? 1)));
      }
      return { episode: ix.episode, score };
    });
    scored.sort(
      (a, b) => b.score - a.score || a.episode.episode_id.localeCompare(b.episode.episode_id),
    );
    return scored.slice(0, K).map((s) => s.episode);
  }

  answer(task: Omit<QaTask, "answer_key" | "evidence_ids" | "distractor_ids">): SystemAnswer {
    const top = this.retrieve(task.question);
    const anchor = top[0];
    const evidence = top.map((e) => e.episode_id);

    switch (task.task_type) {
      case "direct_recall":
        return {
          task_id: task.task_id,
          evidence_ids: evidence,
          answer_key: anchor
            ? { outcome: anchor.resolution.outcome, outcome_status: anchor.resolution.outcome_status }
            : {},
        };
      case "rationale_lookup":
        return {
          task_id: task.task_id,
          evidence_ids: evidence,
          answer_key: anchor
            ? {
                override_reason: anchor.resolution.override_reason,
                trigger_event_type: anchor.trigger.event_type,
                recommended_option: anchor.procedural_path.recommended_option,
              }
            : {},
        };
      case "rule_attribution":
        return {
          task_id: task.task_id,
          evidence_ids: evidence,
          answer_key: anchor ? { semantic_refs: anchor.semantic_refs } : {},
        };
      case "temporal_ordering": {
        if (!anchor) return { task_id: task.task_id, evidence_ids: [], answer_key: {} };
        const hh = `${anchor.household_ref.archetype_id}|${anchor.household_ref.seed}`;
        const priors = [...this.byId.values()]
          .filter(
            (e) =>
              `${e.household_ref.archetype_id}|${e.household_ref.seed}` === hh &&
              e.month_index < anchor.month_index &&
              anchor.month_index - e.month_index <= 24,
          )
          .sort((a, b) => a.month_index - b.month_index || a.episode_id.localeCompare(b.episode_id))
          .map((e) => e.episode_id);
        return {
          task_id: task.task_id,
          evidence_ids: [anchor.episode_id, ...priors],
          answer_key: { episode_ids: priors },
        };
      }
      case "precedent_search": {
        const reason = /for reason "([^"]+)"/.exec(task.question)?.[1];
        const type = /overrode (\S+) policy/.exec(task.question)?.[1];
        const matches = [...this.byId.values()]
          .filter(
            (e) =>
              !e.resolution.followed_policy &&
              e.resolution.override_reason === reason &&
              e.decision_type === type,
          )
          .sort((a, b) => a.episode_id.localeCompare(b.episode_id));
        return {
          task_id: task.task_id,
          evidence_ids: matches.map((e) => e.episode_id),
          answer_key: {
            episodes: matches.map((e) => ({
              episode_id: e.episode_id,
              outcome_status: e.resolution.outcome_status,
            })),
          },
        };
      }
    }
  }
}
