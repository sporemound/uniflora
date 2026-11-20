import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "acorn";
import { transform } from "esbuild";

const MODULES = ["preview.js", "fragment-assets.mjs", "fragment-room.mjs", "fragment_adapter.mjs",
  "garden_adapter.mjs", "homepage-update.mjs", "map-fallback.mjs"];
const HELPERS = ["OPENAI_ENDPOINT", "OPENAI_MODEL", "OPENAI_REASONING_EFFORTS",
  "selectedProvider", "chatProviderConfigured", "responsesText", "requestOpenAI"];
const MARKER = "// Hypha OpenAI transport: targeted patch, preserving deployed campaign and adapters.";
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const [inputArgument, outputArgument, ...extraArguments] = process.argv.slice(2);
assert.ok(inputArgument && outputArgument && !extraArguments.length,
  "Usage: node tools/patch_live_openai.mjs <input-module-dir> <output-module-dir>");
const inputDirectory = resolve(inputArgument);
const outputDirectory = resolve(outputArgument);
assert.notEqual(inputDirectory, outputDirectory, "Input and output directories must differ");
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const inputNames = await readdir(inputDirectory);
assert.deepEqual(inputNames.filter((name) => /\.(?:js|mjs)$/u.test(name)).sort(), MODULES.slice().sort(),
  "Input must contain the exact seven deployed modules");
let outputNames;
try { outputNames = await readdir(outputDirectory); }
catch (error) { if (error.code !== "ENOENT") throw error; }
assert.ok(!outputNames?.length, "Output directory must be absent or empty");

const originals = Object.fromEntries(await Promise.all(MODULES.map(async (name) =>
  [name, await readFile(resolve(inputDirectory, name))])));
const baseline = originals["preview.js"].toString("utf8");
assert.equal(Buffer.from(baseline).compare(originals["preview.js"]), 0, "Preview must be UTF-8");
assert.ok(!baseline.includes(MARKER), "The input is already patched");
const baselineAst = parse(baseline, { ecmaVersion: "latest", sourceType: "module" });
const functionNode = (name) => {
  const matches = baselineAst.body.filter((node) =>
    node.type === "FunctionDeclaration" && node.id?.name === name);
  assert.equal(matches.length, 1, `Expected exactly one deployed ${name} function`);
  assert.ok(matches[0].body, `${name} must have a body`);
  return matches[0];
};
const bindingNames = (ast) => ast.body.flatMap((node) =>
  node.type === "FunctionDeclaration" && node.id ? [node.id.name]
    : node.type === "VariableDeclaration" ? node.declarations.flatMap((declaration) =>
      declaration.id.type === "Identifier" ? [declaration.id.name] : []) : []);
for (const name of HELPERS) assert.ok(!bindingNames(baselineAst).includes(name),
  `Baseline already declares ${name}`);
assert.match(originals["fragment_adapter.mjs"].toString(), /export\s*\{\s*FragmentRoom\s*\}/u,
  "Deployed Fragment Room export must exist");
assert.match(originals["fragment_adapter.mjs"].toString(), /export\s*\*\s*from\s*['"]\.\/garden_adapter\.mjs['"]/u,
  "Deployed garden adapter re-exports must exist");

const providerSource = await readFile(resolve(root, "worker/lib/preview-chat.ts"), "utf8");
const transpiledProvider = await transform(providerSource, {
  loader: "ts", target: "es2023", format: "esm", minify: false,
  sourcemap: false, legalComments: "none",
});
const providerAst = parse(transpiledProvider.code, { ecmaVersion: "latest", sourceType: "module" });
const helperStatements = HELPERS.map((name) => {
  const matches = providerAst.body.filter((node) =>
    node.type === "FunctionDeclaration" ? node.id?.name === name
      : node.type === "VariableDeclaration" && node.declarations.length === 1 &&
        node.declarations[0].id.type === "Identifier" && node.declarations[0].id.name === name);
  assert.equal(matches.length, 1, `Expected exactly one source helper ${name}`);
  return transpiledProvider.code.slice(matches[0].start, matches[0].end);
}).join("\n\n");
const helperResult = await transform(helperStatements, {
  loader: "ts", target: "es2023", format: "esm", minify: false,
  sourcemap: false, legalComments: "none",
});
const helperCode = helperResult.code;
assert.ok(!/^\s*(?:import|export)\s/mu.test(helperCode), "Transpiled helpers must be self-contained");

const edits = [];
const replaceWithin = (node, anchor, replacement, label) => {
  const start = node.start;
  const text = baseline.slice(start, node.end);
  const first = text.indexOf(anchor);
  assert.ok(first >= 0 && text.indexOf(anchor, first + anchor.length) === -1,
    `Expected one unique ${label} anchor`);
  edits.push({ start: start + first, end: start + first + anchor.length,
    before: anchor, after: replacement, label });
};
edits.push({ start: functionNode("requireChatDatabase").start,
  end: functionNode("requireChatDatabase").start, before: "",
  after: `${MARKER}\n${helperCode}\n`, label: "add-provider-helpers" });
const requestFunction = functionNode("requestGemini");
edits.push({ start: requestFunction.body.start + 1,
  end: requestFunction.body.start + 1, before: "",
  after: `\n  if (!chatProviderConfigured(env)) {\n    throw new HttpError(503, "preview_chat_unconfigured", "Hypha conversation is not configured yet.");\n  }\n  if (selectedProvider(env) === "openai") {\n    return requestOpenAI(env, systemInstruction, input, maxOutputTokens);\n  }`,
  label: "route-selected-provider" });
replaceWithin(functionNode("handlePreviewChat"),
  'if (replyMode === "hypha" && !env.GEMINI_API_KEY?.trim())',
  'if (replyMode === "hypha" && !chatProviderConfigured(env))', "hypha-post-readiness");
replaceWithin(functionNode("guestDemoConfigured"), "env.GEMINI_API_KEY?.trim()",
  "chatProviderConfigured(env)", "guest-readiness");
replaceWithin(functionNode("api"),
  "chatReady: Boolean((emailReady || guestReady) && chatSchemaReady && env.GEMINI_API_KEY?.trim())",
  "chatReady: Boolean((emailReady || guestReady) && chatSchemaReady && chatProviderConfigured(env))",
  "health-readiness");
edits.sort((a, b) => a.start - b.start);
assert.equal(edits.length, 5, "Only the expected five targeted edits are allowed");
let previousEnd = 0;
for (const edit of edits) {
  assert.ok(edit.start >= previousEnd, "Patch edits must not overlap");
  assert.equal(baseline.slice(edit.start, edit.end), edit.before, "Patch baseline changed");
  previousEnd = edit.end;
}
let patched = baseline;
for (const edit of edits.slice().reverse()) {
  patched = patched.slice(0, edit.start) + edit.after + patched.slice(edit.end);
}
let delta = 0;
const reverseEdits = edits.map((edit) => {
  const start = edit.start + delta;
  delta += edit.after.length - edit.before.length;
  return { start, end: start + edit.after.length, after: edit.before };
});
let restored = patched;
for (const edit of reverseEdits.reverse()) {
  restored = restored.slice(0, edit.start) + edit.after + restored.slice(edit.end);
}
assert.equal(restored, baseline, "Reversing only intended edits must restore every baseline byte");
const patchedAst = parse(patched, { ecmaVersion: "latest", sourceType: "module" });
const exportsOf = (ast, source) => ast.body.filter((node) =>
  ["ExportNamedDeclaration", "ExportDefaultDeclaration", "ExportAllDeclaration"].includes(node.type))
  .map((node) => source.slice(node.start, node.end));
assert.deepEqual(exportsOf(patchedAst, patched), exportsOf(baselineAst, baseline),
  "Existing preview exports must remain exact");
const allowedChangedFunctions = new Set(["requestGemini", "handlePreviewChat", "guestDemoConfigured", "api"]);
for (const originalNode of baselineAst.body) {
  if (originalNode.type === "FunctionDeclaration" && originalNode.id &&
      !allowedChangedFunctions.has(originalNode.id.name)) {
    const replacement = patchedAst.body.find((node) =>
      node.type === "FunctionDeclaration" && node.id?.name === originalNode.id.name);
    assert.ok(replacement, `Unrelated function ${originalNode.id.name} must remain present`);
    assert.equal(patched.slice(replacement.start, replacement.end), baseline.slice(originalNode.start, originalNode.end),
      `Unrelated function ${originalNode.id.name} must remain byte-identical`);
  }
}

await mkdir(outputDirectory, { recursive: true });
const moduleHashes = [];
for (const name of MODULES) {
  const bytes = name === "preview.js" ? Buffer.from(patched) : originals[name];
  await writeFile(resolve(outputDirectory, name), bytes);
  const written = await readFile(resolve(outputDirectory, name));
  assert.equal(written.compare(bytes), 0, `Written module ${name} must match`);
  moduleHashes.push({ name, baselineSha256: sha256(originals[name]), sha256: sha256(written),
    changed: name === "preview.js" });
}
const manifest = { version: 1, inputDirectory, outputDirectory,
  providerSourceSha256: sha256(providerSource), helperCodeSha256: sha256(helperCode),
  edits: edits.map(({ label, start, end, before, after }) => ({ label, start, end, before, after })),
  modules: moduleHashes };
const manifestPath = `${outputDirectory}.manifest.json`;
await writeFile(manifestPath, JSON.stringify(manifest, null, 2) + "\n");
assert.deepEqual((await readdir(outputDirectory)).sort(), MODULES.slice().sort(),
  "Output must contain only seven deployment modules, with no debug extract");
console.log(JSON.stringify({ outputDirectory, manifestPath,
  edits: manifest.edits.map(({ label, start, end }) => ({ label, start, end })),
  modules: moduleHashes }, null, 2));
