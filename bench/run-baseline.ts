/**
 * DecisionSynth Bench — run the built-in lexical baseline.
 *
 * Usage:
 *   npx tsx bench/run-baseline.ts <episodes.json> <qa.json> <out-answers.json>
 *
 * Reads the corpus, strips all ground truth from the tasks (adapters never
 * see answer keys, evidence ids, or distractors), runs the baseline, and
 * writes the SystemAnswer file that bench/score.ts consumes.
 */

import fs from "fs";
import path from "path";
import type { EpisodeRecord, QaTask, SystemAnswer } from "./types";
import { NaiveLexicalBaseline } from "./adapters/naive-baseline";

async function main() {
  const [episodesPath, qaPath, outPath] = process.argv.slice(2);
  if (!episodesPath || !qaPath || !outPath) {
    console.error("usage: run-baseline.ts <episodes.json> <qa.json> <out-answers.json>");
    process.exit(2);
  }

  const episodes = (JSON.parse(fs.readFileSync(episodesPath, "utf-8")) as {
    episodes: EpisodeRecord[];
  }).episodes;
  const tasks = (JSON.parse(fs.readFileSync(qaPath, "utf-8")) as { qa_tasks: QaTask[] }).qa_tasks;

  const adapter = new NaiveLexicalBaseline();
  await adapter.ingest(episodes);

  const answers: SystemAnswer[] = [];
  for (const task of tasks) {
    // Strip ground truth — adapters only ever see the question.
    answers.push(
      await adapter.answer({
        task_id: task.task_id,
        task_type: task.task_type,
        question: task.question,
      }),
    );
  }

  fs.mkdirSync(path.dirname(path.resolve(outPath)), { recursive: true });
  fs.writeFileSync(
    outPath,
    JSON.stringify({ system: adapter.name, answers }, null, 2) + "\n",
  );
  console.log(`${adapter.name}: answered ${answers.length} tasks over ${episodes.length} episodes → ${outPath}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
