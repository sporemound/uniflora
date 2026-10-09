import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const packagePath = path.join(root, "package.json");
const packageJson = JSON.parse(await readFile(packagePath, "utf8"));
packageJson.scripts ??= {};
packageJson.scripts["validate:phase4b"] = "node tools/validate_phase4b.mjs";
await writeFile(packagePath, `${JSON.stringify(packageJson, null, 2)}\n`, "utf8");
console.log("Registered npm run validate:phase4b without changing dependencies.");
