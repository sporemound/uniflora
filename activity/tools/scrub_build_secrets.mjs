import { rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const activityRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const generatedWorkerRoot = path.join(
  activityRoot,
  "dist",
  "missing_interior_activity",
);
const forbiddenBuildFiles = [
  ".dev.vars",
  ".env",
  ".env.local",
  ".env.production",
  ".env.production.local",
];

for (const filename of forbiddenBuildFiles) {
  const target = path.resolve(generatedWorkerRoot, filename);
  if (!target.startsWith(`${generatedWorkerRoot}${path.sep}`)) {
    throw new Error(`Refusing to scrub a path outside the generated Worker: ${target}`);
  }
  await rm(target, { force: true });
}

console.log("Scrubbed environment and dev-var files from the generated Worker.");
