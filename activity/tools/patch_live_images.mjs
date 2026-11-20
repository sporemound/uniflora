import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "acorn";
import { transform } from "esbuild";

const MODULES = ["preview.js", "fragment-assets.mjs", "fragment-room.mjs", "fragment_adapter.mjs",
  "garden_adapter.mjs", "homepage-update.mjs", "map-fallback.mjs"];
const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const [input, output, ...extra] = process.argv.slice(2);
assert.ok(input && output && !extra.length,
  "Usage: node tools/patch_live_images.mjs <input-module-dir> <output-module-dir>");
const inputDirectory = resolve(input);
const outputDirectory = resolve(output);
assert.notEqual(inputDirectory, outputDirectory);
assert.deepEqual((await readdir(inputDirectory)).filter((n) => /\.(?:js|mjs)$/u.test(n)).sort(), MODULES.slice().sort());
try { assert.equal((await readdir(outputDirectory)).length, 0, "Output must be absent or empty"); }
catch (error) { if (error.code !== "ENOENT") throw error; }
const modules = Object.fromEntries(await Promise.all(MODULES.map(async (name) =>
  [name, await readFile(resolve(inputDirectory, name), "utf8")])));
const baseline = modules["preview.js"];
const ast = parse(baseline, { ecmaVersion: "latest", sourceType: "module" });
const nodeFor = (name) => {
  const matches = ast.body.filter((node) => node.type === "FunctionDeclaration" && node.id?.name === name);
  assert.equal(matches.length, 1, `Expected one ${name}`);
  return matches[0];
};
const oldGenerator = nodeFor("generateViaGoogleFlowApi");
const handler = nodeFor("handleStatementClockPlates");
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const providerSource = await readFile(resolve(root, "worker/lib/low-cost-image.ts"), "utf8");
const { code } = await transform(providerSource, { loader: "ts", target: "es2023", format: "esm",
  minify: false, sourcemap: false, legalComments: "none" });
const providerAst = parse(code, { ecmaVersion: "latest", sourceType: "module" });
const names = new Set(ast.body.flatMap((node) => node.id ? [node.id.name] :
  node.type === "VariableDeclaration" ? node.declarations.map((d) => d.id.name) : []));
const declarations = [];
for (const node of providerAst.body) {
  if (node.type === "ImportDeclaration") {
    assert.equal(node.source.value, "./errors");
    assert.deepEqual(node.specifiers.map((s) => s.local.name), ["HttpError"]);
    continue;
  }
  if (node.type === "ExportNamedDeclaration" && !node.declaration) continue;
  const declaration = node.type === "ExportNamedDeclaration" ? node.declaration : node;
  const declared = declaration.id ? [declaration.id.name] :
    declaration.type === "VariableDeclaration" ? declaration.declarations.map((d) => d.id.name) : [];
  for (const name of declared) assert.ok(!names.has(name), `Provider helper collides with ${name}`);
  declarations.push(code.slice(declaration.start, declaration.end));
}
let updatedHandler = baseline.slice(handler.start, handler.end);
const replaceOnce = (before, after) => {
  assert.equal(updatedHandler.split(before).length, 2, `Expected exact image handler anchor: ${before.slice(0, 70)}`);
  updatedHandler = updatedHandler.replace(before, after);
};
replaceOnce("const hasLiveApiKey = Boolean(env.GEMINI_API_KEY?.trim());",
  "const hasLiveApiKey = imageProviderConfigured(env);");
const generationStart = updatedHandler.indexOf("  const apiKey = env.GEMINI_API_KEY?.trim();");
const generationEnd = updatedHandler.indexOf("  const usedNumbers =", generationStart);
assert.ok(generationStart >= 0 && generationEnd > generationStart);
const oldGeneration = updatedHandler.slice(generationStart, generationEnd);
assert.ok(oldGeneration.includes("generateViaGoogleFlowApi(apiKey, prompt, deterministicSeed)"));
replaceOnce(oldGeneration,
  "  const generated = await generateLowCostImage(env, prompt, await sha256Hex(`hypha-image:${subjectId}`));\n" +
  "  imageUrl2 = generated.dataUrl;\n  modelUsed = generated.modelUsed;\n");
assert.ok(updatedHandler.includes("if (rows.length >= MAX_PLATES_PER_USER)"));
assert.ok(updatedHandler.indexOf("if (rows.length >= MAX_PLATES_PER_USER)") < updatedHandler.indexOf("await generateLowCostImage"));
const edits = [
  { start: oldGenerator.start, end: oldGenerator.end,
    before: baseline.slice(oldGenerator.start, oldGenerator.end), after: declarations.join("\n"), label: "one-image-provider-request" },
  { start: handler.start, end: handler.end, before: baseline.slice(handler.start, handler.end),
    after: updatedHandler, label: "reuse-existing-plate-quota-and-storage" },
].sort((a, b) => a.start - b.start);
let patched = baseline;
for (const { start, end, before, after } of edits.slice().reverse()) {
  assert.equal(baseline.slice(start, end), before);
  patched = patched.slice(0, start) + after + patched.slice(end);
}
// esbuild emits a separate harmless name annotation after each original function.
patched = patched.replace('__name(generateViaGoogleFlowApi, "generateViaGoogleFlowApi");', "");
const patchedAst = parse(patched, { ecmaVersion: "latest", sourceType: "module" });
for (const node of ast.body) {
  if (node.type !== "FunctionDeclaration" || ["generateViaGoogleFlowApi", "handleStatementClockPlates"].includes(node.id?.name)) continue;
  const same = patchedAst.body.find((candidate) => candidate.type === "FunctionDeclaration" && candidate.id?.name === node.id?.name);
  assert.ok(same);
  assert.equal(patched.slice(same.start, same.end), baseline.slice(node.start, node.end), `Unrelated function changed: ${node.id.name}`);
}
assert.match(patched, /var MAX_PLATES_PER_USER = 6;/u);
assert.ok(!patched.includes("async function generateViaGoogleFlowApi("));

// Update only disclosure text in the already pinned public JavaScript bundle.
// The fax renderer, overlay, prompts, existing plates and six-image controls stay exact.
const replacements = [
  ["Chat questions are sent to Google Gemini to generate replies. Google's use of Gemini API content for product improvement, including model training, depends on the project's API billing tier: unpaid-tier content may be used for that purpose; Google says paid-tier prompts and responses are not. The public record and sending a submitted chat question to Gemini are part of participating in those features.",
    "Chat questions and recent shared chat are sent to OpenAI to generate replies. Exposing a latent plate sends its image prompt to OpenAI; generated plates appear in Hypha Chat. The public record and sending submitted questions or image prompts to OpenAI are part of participating in those features."],
  ["Your question is also sent to Google Gemini, which may use free-tier requests to improve its products.", "Your question is also sent to OpenAI to generate a reply."],
  ["Shared visibility, Gemini context & speech playback", "Shared visibility, OpenAI context & speech playback"],
  ["A Hypha reply sends your message and recent shared chat to Google Gemini.", "A Hypha reply sends your message and recent shared chat to OpenAI. Exposing a latent plate sends its image prompt to OpenAI."],
  ["Decrypt this absent room into Hypha Chat as a deterministic color facsimile plate (up to 6 plates per 24 hours).", "Decrypt this absent room into Hypha Chat as a color facsimile plate (up to 6 plates per 24 hours)."],
];
const homepageBefore = modules["homepage-update.mjs"];
const homepageAnchor = `  const body = text.replace(preload, '"' + UI_PREFIX.slice(1) + MAP_NAME + '"');`;
assert.equal(homepageBefore.split(homepageAnchor).length, 2);
modules["homepage-update.mjs"] = homepageBefore.replace(homepageAnchor,
  `  const copyUpdates = ${JSON.stringify(replacements)};\n` +
  `  let body = text.replace(preload, '"' + UI_PREFIX.slice(1) + MAP_NAME + '"');\n` +
  "  for (const [before, after] of copyUpdates) body = body.replace(before, after);");
parse(modules["homepage-update.mjs"], { ecmaVersion: "latest", sourceType: "module" });
modules["preview.js"] = patched;
await mkdir(outputDirectory, { recursive: true });
const hashes = [];
for (const name of MODULES) {
  const before = await readFile(resolve(inputDirectory, name));
  await writeFile(resolve(outputDirectory, name), modules[name]);
  hashes.push({ name, baselineSha256: sha256(before), sha256: sha256(modules[name]),
    changed: !before.equals(Buffer.from(modules[name])) });
}
const manifestPath = `${outputDirectory}.manifest.json`;
await writeFile(manifestPath, JSON.stringify({ version: 1, inputDirectory, outputDirectory, edits,
  modules: hashes, copyUpdates: replacements, providerSourceSha256: sha256(providerSource) }, null, 2) + "\n");
console.log(JSON.stringify({ outputDirectory, manifestPath, modules: hashes }, null, 2));
