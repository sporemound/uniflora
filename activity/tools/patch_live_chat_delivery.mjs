import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "acorn";
import { transform } from "esbuild";

const MODULES = ["preview.js", "fragment-assets.mjs", "fragment-room.mjs", "fragment_adapter.mjs",
  "garden_adapter.mjs", "homepage-update.mjs", "map-fallback.mjs"];
const NOTICE = "Connection notice: Your message was saved, but Hypha cannot reply right now.";
const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const [inputArgument, outputArgument, ...extra] = process.argv.slice(2);
assert.ok(inputArgument && outputArgument && !extra.length,
  "Usage: node tools/patch_live_chat_delivery.mjs <input-module-dir> <output-module-dir>");
const inputDirectory = resolve(inputArgument);
const outputDirectory = resolve(outputArgument);
assert.notEqual(inputDirectory, outputDirectory);
assert.deepEqual((await readdir(inputDirectory)).filter((name) => /\.(?:js|mjs)$/u.test(name)).sort(), MODULES.slice().sort());
let existing;
try { existing = await readdir(outputDirectory); }
catch (error) { if (error.code !== "ENOENT") throw error; }
assert.ok(!existing?.length, "Output directory must be absent or empty");
const modules = Object.fromEntries(await Promise.all(MODULES.map(async (name) =>
  [name, await readFile(resolve(inputDirectory, name))])));
const baseline = modules["preview.js"].toString("utf8");
assert.equal(Buffer.from(baseline).compare(modules["preview.js"]), 0);
const ast = parse(baseline, { ecmaVersion: "latest", sourceType: "module" });
const functionNode = (name) => {
  const matches = ast.body.filter((node) => node.type === "FunctionDeclaration" && node.id?.name === name);
  assert.equal(matches.length, 1, `Expected one ${name} function`);
  return matches[0];
};
const handler = functionNode("handlePreviewChat");
const originalHandler = baseline.slice(handler.start, handler.end);
assert.ok(!originalHandler.includes(NOTICE), "Delivery handling is already patched");
let updatedHandler = originalHandler;
const replaceExactly = (before, after, label) => {
  assert.equal(updatedHandler.split(before).length, 2, `Expected one ${label} anchor`);
  updatedHandler = updatedHandler.replace(before, after);
};
replaceExactly(`  if (replyMode === "hypha" && !chatProviderConfigured(env)) {\n    throw new HttpError(503, "preview_chat_unconfigured", "Hypha replies are not configured yet.");\n  }\n`, "", "early-provider-gate");
const inferenceBlock = `  const currentGame = await availableHyphaGameActions(request, env, profile.roleId, true);\n  const gameActions = currentGame?.suggestions.length ? currentGame : null;\n  const answer = await geminiReply(request, env, message, history, gameActions);\n  const reply = boundedReply(answer.reply, mode);\n`;
replaceExactly(inferenceBlock, "", "inference-before-save");
const notices = {
  chat_unavailable: NOTICE,
  chat_credit_exhausted: "Connection notice: Hypha cannot reply because its API credits are unavailable. Your message was saved.",
  chat_credentials_rejected: "Connection notice: Hypha's API credentials were rejected. Your message was saved.",
  chat_model_unavailable: "Connection notice: Hypha's AI model is unavailable. Your message was saved.",
  chat_request_rejected: "Connection notice: Hypha's AI service rejected this request. Your message was saved.",
  chat_provider_rate_limited: "Connection notice: Hypha's AI service is busy. Your message was saved. Please try again shortly.",
};
const guardedInference = `  let gameActions = null;\n  let answer = { reply: "", selectedIndex: null };\n  let reply;\n  let failed = false;\n  let replyError = null;\n  try {\n    if (!chatProviderConfigured(env)) {\n      throw new HttpError(503, "preview_chat_unconfigured", "Hypha replies are not configured yet.");\n    }\n    const currentGame = await availableHyphaGameActions(request, env, profile.roleId, true);\n    gameActions = currentGame?.suggestions.length ? currentGame : null;\n    answer = await geminiReply(request, env, message, history, gameActions);\n    reply = boundedReply(answer.reply, mode);\n  } catch (error) {\n    failed = true;\n    const notices = ${JSON.stringify(notices)};\n    const code = error instanceof HttpError && Object.hasOwn(notices, error.code)\n      ? error.code : "chat_unavailable";\n    replyError = { code, status: 503 };\n    reply = notices[code];\n  }\n`;
replaceExactly("  await completeHyphaChatRequest(env.CHAT_DB, {", `${guardedInference}  await completeHyphaChatRequest(env.CHAT_DB, {`, "inference-after-save");
replaceExactly("    failed: false\n  });", "    failed\n  });", "failed-completion");
replaceExactly("  if (gameActions && answer.selectedIndex !== null && profile.roleId) {",
  "  if (!failed && gameActions && answer.selectedIndex !== null && profile.roleId) {", "proposal-guard");
replaceExactly("  if (waitUntil) {", "  if (!failed && waitUntil) {", "audio-guard");
replaceExactly("    gameActionProposal\n  }, 201);", "    gameActionProposal,\n    replyError\n  }, 201);", "safe-reply-error");
assert.ok(updatedHandler.indexOf("const history = await recentSharedHistory") <
  updatedHandler.indexOf("await createHyphaChatRequest"), "Read history before inserting the current message");
assert.ok(updatedHandler.indexOf("await createHyphaChatRequest") <
  updatedHandler.indexOf("await availableHyphaGameActions"), "Persist before game and inference networking");

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const providerSource = await readFile(resolve(root, "worker/lib/preview-chat.ts"), "utf8");
const transpiled = await transform(providerSource, { loader: "ts", target: "es2023", format: "esm",
  minify: false, sourcemap: false, legalComments: "none" });
const sourceAst = parse(transpiled.code, { ecmaVersion: "latest", sourceType: "module" });
const providerFunctions = sourceAst.body.filter((node) => node.type === "FunctionDeclaration" &&
  node.id?.name === "requestOpenAI");
assert.equal(providerFunctions.length, 1);
const provider = functionNode("requestOpenAI");
const edits = [{ start: handler.start, end: handler.end, before: originalHandler, after: updatedHandler,
  label: "persist-before-inference-and-save-visible-failures" },
{ start: provider.start, end: provider.end, before: baseline.slice(provider.start, provider.end),
  after: transpiled.code.slice(providerFunctions[0].start, providerFunctions[0].end),
  label: "safe-provider-status-diagnostics" }].sort((a, b) => a.start - b.start);
let patched = baseline;
for (const { start, end, before, after } of edits.slice().reverse()) {
  assert.equal(baseline.slice(start, end), before);
  patched = patched.slice(0, start) + after + patched.slice(end);
}
const patchedAst = parse(patched, { ecmaVersion: "latest", sourceType: "module" });
for (const node of ast.body) {
  if (node.type === "FunctionDeclaration" && !["handlePreviewChat", "requestOpenAI"].includes(node.id?.name)) {
    const updated = patchedAst.body.find((candidate) => candidate.type === "FunctionDeclaration" &&
      candidate.id?.name === node.id?.name);
    assert.ok(updated);
    assert.equal(patched.slice(updated.start, updated.end), baseline.slice(node.start, node.end),
      `Unrelated function ${node.id?.name} must stay exact`);
  }
}
const exportsOf = (tree, text) => tree.body.filter((node) => /^Export/u.test(node.type))
  .map((node) => text.slice(node.start, node.end));
assert.deepEqual(exportsOf(patchedAst, patched), exportsOf(ast, baseline));
await mkdir(outputDirectory, { recursive: true });
const hashes = [];
for (const name of MODULES) {
  const bytes = name === "preview.js" ? Buffer.from(patched) : modules[name];
  await writeFile(resolve(outputDirectory, name), bytes);
  assert.equal((await readFile(resolve(outputDirectory, name))).compare(bytes), 0);
  hashes.push({ name, baselineSha256: sha256(modules[name]), sha256: sha256(bytes),
    changed: name === "preview.js" });
}
const manifestPath = `${outputDirectory}.manifest.json`;
await writeFile(manifestPath, JSON.stringify({ version: 1, inputDirectory, outputDirectory, edits,
  modules: hashes, providerSourceSha256: sha256(providerSource) }, null, 2) + "\n");
console.log(JSON.stringify({ outputDirectory, manifestPath,
  edits: edits.map(({ start, end, label }) => ({ start, end, label })), modules: hashes }, null, 2));
