import assert from "node:assert/strict";
import { createHash, webcrypto } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import vm from "node:vm";
import { parse } from "acorn";

const [argument, clientArgument, ...extra] = process.argv.slice(2);
assert.ok(argument && !extra.length,
  "Usage: node tools/validate_live_images.mjs <patched-module-dir> [captured-client-js]");
const directory = resolve(argument);
const clientPath = clientArgument ? resolve(clientArgument)
  : resolve(directory, "..", "hypha-client-review/index-DedbkRi2.js");
const manifest = JSON.parse(await readFile(`${directory}.manifest.json`, "utf8"));
const sha256 = (value) => createHash("sha256").update(value).digest("hex");
assert.equal(manifest.modules.length, 7);
assert.equal(manifest.edits.length, 2);
assert.deepEqual((await readdir(directory)).sort(), manifest.modules.map(({ name }) => name).sort());
assert.deepEqual(manifest.modules.filter(({ changed }) => changed).map(({ name }) => name).sort(),
  ["homepage-update.mjs", "preview.js"]);
for (const { name, baselineSha256, sha256: expected, changed } of manifest.modules) {
  const bytes = await readFile(resolve(directory, name));
  const original = await readFile(resolve(manifest.inputDirectory, name));
  assert.equal(sha256(bytes), expected);
  assert.equal(sha256(original), baselineSha256);
  if (!changed) assert.equal(bytes.compare(original), 0, `${name} stays byte-identical`);
}
const source = await readFile(resolve(directory, "preview.js"), "utf8");
const original = await readFile(resolve(manifest.inputDirectory, "preview.js"), "utf8");
let reapplied = original;
for (const { start, end, before, after } of manifest.edits.slice().reverse()) {
  assert.equal(original.slice(start, end), before);
  reapplied = reapplied.slice(0, start) + after + reapplied.slice(end);
}
reapplied = reapplied.replace('__name(generateViaGoogleFlowApi, "generateViaGoogleFlowApi");', "");
assert.equal(reapplied, source, "Only the two declared image edits and obsolete annotation removal are applied");
const astFor = (text) => parse(text, { ecmaVersion: "latest", sourceType: "module" });
const originalAst = astFor(original);
const patchedAst = astFor(source);
const functionMap = (text, ast) => new Map(ast.body
  .filter((node) => node.type === "FunctionDeclaration" && node.id)
  .map((node) => [node.id.name, text.slice(node.start, node.end)]));
const baselineFunctions = functionMap(original, originalAst);
const patchedFunctions = functionMap(source, patchedAst);
for (const [name, text] of baselineFunctions) {
  if (!["generateViaGoogleFlowApi", "handleStatementClockPlates"].includes(name)) {
    assert.equal(patchedFunctions.get(name), text, `Unrelated function stays exact: ${name}`);
  }
}
assert.equal(patchedFunctions.has("generateViaGoogleFlowApi"), false);
assert.equal(patchedFunctions.get("buildAbsentRoomPrompt"), baselineFunctions.get("buildAbsentRoomPrompt"));
assert.match(patchedFunctions.get("buildAbsentRoomPrompt"), /encrypted color fax machine/u);
assert.match(patchedFunctions.get("buildAbsentRoomPrompt"), /cipher-burst telemetry bars/u);
assert.match(patchedFunctions.get("buildAbsentRoomPrompt"), /halftoned thermal-dye color transfer texture/u);

// Execute the actual patched functions in an isolated VM, with only identity and
// D1/network boundaries mocked. The rolling plate-window implementation is real.
const selectedFunctions = new Set([
  "ensurePlateSchema", "computeDeterministicFlowSeed", "resolveAbsentRoomEraContext", "buildAbsentRoomPrompt",
  "serializeCursor", "upsertClockCursor", "serializePlate", "loadBestCursorForSubject", "loadPlatesForSubject",
  "handleStatementClockPlates", "imageProviderConfigured", "imageUnavailable", "boundedImageResponse",
  "imageServiceError", "jpegBase64", "generateLowCostImage",
]);
const selectedVariables = new Set([
  "MAX_PLATES_PER_USER", "schemaBootstrapped", "PROMPT_ERA_VERSION", "LOWER_BASEMENT_PATTERNS",
  "MODERN_INTERIOR_PATTERNS", "PLATE_WINDOW_MS", "IMAGE_ENDPOINT", "IMAGE_MODEL", "MAX_PROMPT_CHARACTERS",
  "MAX_IMAGE_BYTES", "HYPHA_IMAGE_MAX_RESPONSE_BYTES", "MAX_BASE64_CHARACTERS",
]);
const extracted = patchedAst.body.filter((node) => node.type === "FunctionDeclaration"
  ? selectedFunctions.has(node.id?.name)
  : node.type === "VariableDeclaration" && node.declarations.some((item) => selectedVariables.has(item.id.name)));
assert.equal(extracted.filter((node) => node.type === "FunctionDeclaration").length, selectedFunctions.size);
const extractedSource = extracted.map((node) => source.slice(node.start, node.end)).join("\n");
class TestHttpError extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}
const origin = "https://uniflora.garden";
const subjectId = "user:private-subject";
const jpeg = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0, 2, 0xff, 0xd9]).toString("base64");
const requestBody = { seed: "boundary-event", step: 8, combinationIndex: 19,
  statementText: "An inner-switching alcove emits a displaced carrier.", autoCycle: false };
let current;
let network = async () => Response.json({ data: [{ b64_json: jpeg }] });
const context = vm.createContext({
  Request, Response, Headers, URL, AbortSignal, TextDecoder, TextEncoder, Uint8Array,
  Date, Math, Set, Number, Boolean, Array, JSON, crypto: webcrypto, atob, btoa,
  HttpError: TestHttpError,
  jsonResponse: (value, status = 200) => Response.json(value, { status }),
  methodNotAllowed: (allowed) => new Response(null, { status: 405, headers: { Allow: allowed.join(", ") } }),
  requireSameOriginMutation: (request) => {
    assert.equal(request.headers.get("Origin"), origin);
  },
  resolveSubjectIdentities: async () => ({ primarySubjectId: subjectId, guestSubjectId: "guest:current", legacyGuestSubjectId: "guest:legacy" }),
  sha256Hex: async (text) => sha256(text),
  fetch: async (...args) => { current.calls.push(args); return network(...args); },
});
vm.runInContext(`${extractedSource}\nglobalThis.testImageHandler = handleStatementClockPlates;`, context);
function fixture(rows = []) {
  const state = { rows: structuredClone(rows), cursors: new Map(), calls: [], saved: 0, deletes: 0 };
  const db = { prepare(sql) {
    return { values: [], bind(...values) { this.values = values; return this; },
      async run() {
        const v = this.values;
        if (sql.includes("CREATE TABLE")) return { success: true, meta: { changes: 0 } };
        if (sql.includes("DELETE FROM statement_clock_plates")) {
          const before = state.rows.length;
          state.rows = state.rows.filter((row) => row.subject_id !== v[0] ||
            (row.created_at >= v[1] && (!sql.includes("model_used") ||
              row.model_used.includes("era-v2") && !row.image_url.startsWith("data:image/svg+xml"))));
          state.deletes += before - state.rows.length;
        } else if (sql.includes("INSERT INTO statement_clock_plates")) {
          state.saved += 1;
          state.rows.push(Object.fromEntries(["plate_id", "subject_id", "plate_number", "seed_text", "step_index",
            "combination_index", "deterministic_seed", "statement_text", "image_url", "model_used", "created_at"]
            .map((key, index) => [key, v[index]])));
        } else if (sql.includes("INSERT INTO statement_clock_cursors")) {
          state.cursors.set(v[0], { subject_id: v[0], seed_text: v[1], step_index: v[2], auto_cycle: v[3], updated_at: v[4] });
        } else throw new Error(`Unexpected write: ${sql}`);
        return { success: true, meta: { changes: 1 } };
      },
      async all() {
        assert.ok(sql.includes("FROM statement_clock_plates"));
        return { results: state.rows.filter((row) => row.subject_id === this.values[0] && row.created_at >= this.values[1])
          .sort((a, b) => a.created_at.localeCompare(b.created_at) || a.plate_number - b.plate_number) };
      },
      async first() {
        assert.ok(sql.includes("FROM statement_clock_cursors"));
        return state.cursors.get(this.values[0]) ?? null;
      },
    };
  } };
  state.env = { PUBLIC_DB: db, OPENAI_API_KEY: "test-key-never-log", OPENAI_PRIVACY_ACKNOWLEDGED: "true" };
  return state;
}
const existingPlate = (index, ageHours = 1) => ({ plate_id: `existing-${index}`, subject_id: subjectId,
  plate_number: index + 1, seed_text: "original", step_index: index, combination_index: index,
  deterministic_seed: index + 100, statement_text: `Archived room ${index}`, image_url: `data:image/png;base64,original-${index}`,
  model_used: "gemini-2.5-flash-image (deterministic-seed, era-v2)", created_at: new Date(Date.now() - ageHours * 3600_000).toISOString() });
const call = (method = "POST", body = requestBody) => context.testImageHandler(new Request(`${origin}/api/statement-clock/plates`, {
  method, headers: { Origin: origin, "Content-Type": "application/json" },
  ...(method === "GET" ? {} : { body: JSON.stringify(body) }),
}), current.env);
let cases = 0;
current = fixture([existingPlate(0)]);
const archived = structuredClone(current.rows[0]);
let response = await call("GET");
assert.equal(response.status, 200);
let payload = await response.json();
assert.equal(payload.limit, 6); assert.equal(payload.windowHours, 24);
assert.equal(payload.usedCount, 1); assert.equal(payload.remainingCount, 5);
assert.equal(payload.plates[0].imageUrl, archived.image_url);
assert.equal(current.calls.length, 0); assert.equal(current.saved, 0); cases += 1;
response = await call();
assert.equal(response.status, 201);
payload = await response.json();
assert.equal(payload.usedCount, 2); assert.equal(payload.remainingCount, 4);
assert.equal(payload.plate.imageUrl, `data:image/jpeg;base64,${jpeg}`);
assert.equal(payload.plate.modelUsed, "gpt-image-2.6-flare (high, era-v2)");
assert.equal(current.saved, 1); assert.equal(current.calls.length, 1);
assert.deepEqual(current.rows[0], archived, "Previously exposed images remain byte-for-byte unchanged");
const [endpoint, options] = current.calls[0];
assert.equal(endpoint, "https://api.openai.com/v1/images/generations");
const submitted = JSON.parse(options.body);
const realPrompt = vm.runInContext(`buildAbsentRoomPrompt(${JSON.stringify(requestBody.statementText)}, ${payload.plate.deterministicSeed})`, context);
assert.deepEqual(submitted, { model: "gpt-image-2.6-flare", prompt: realPrompt, n: 1, size: "1536x864",
  quality: "high", output_format: "jpeg", output_compression: 100, moderation: "auto", safety_identifier: sha256(`hypha-image:${subjectId}`) });
assert.equal(options.headers.Authorization, "Bearer test-key-never-log");
assert.ok(!options.body.includes(subjectId)); cases += 1;

current = fixture(Array.from({ length: 6 }, (_, i) => existingPlate(i)));
await assert.rejects(call(), (error) => error.code === "plate_limit_reached" && error.status === 429);
assert.equal(current.calls.length, 0); assert.equal(current.saved, 0); assert.equal(current.rows.length, 6); cases += 1;
current = fixture([existingPlate(0)]);
await assert.rejects(call("POST", { ...requestBody, statementText: "Archived room 0" }),
  (error) => error.code === "duplicate_plate_exposure");
assert.equal(current.calls.length, 0); assert.equal(current.saved, 0); cases += 1;
current = fixture([existingPlate(0)]);
const beforeCreditFailure = structuredClone(current.rows);
network = async () => Response.json({ error: { code: "credit_balance_exhausted", message: "PRIVATE_PROVIDER_MESSAGE" } }, { status: 429 });
await assert.rejects(call(), (error) => error.code === "image_credit_exhausted" && !error.message.includes("PRIVATE_PROVIDER_MESSAGE"));
assert.equal(current.calls.length, 1); assert.equal(current.saved, 0);
assert.deepEqual(current.rows, beforeCreditFailure, "Credit failures leave existing plates and remaining allowance intact"); cases += 1;
// The pre-existing rolling window is retained: six archived plates older than
// 24 hours expire, allowing a new exposure without introducing a new quota.
current = fixture(Array.from({ length: 6 }, (_, i) => existingPlate(i, 25)));
network = async () => Response.json({ data: [{ b64_json: jpeg }] });
response = await call();
assert.equal(response.status, 201); assert.equal(current.deletes, 6);
assert.equal(current.saved, 1); assert.equal(current.calls.length, 1); cases += 1;

// Exercise the actual homepage asset-transform module against the captured
// production UI. Exact equality proves the fax renderer, overlay and controls
// are untouched beyond the enumerated disclosure/title text replacements.
const homepage = await import(pathToFileURL(resolve(directory, "homepage-update.mjs")).href);
const client = await readFile(clientPath, "utf8");
const uiRequest = new Request(`${origin}${homepage.UI_PREFIX}${homepage.ENTRY_NAME}`);
const served = await homepage.serveHomepageUpdateAsset(uiRequest, { ASSETS: { fetch: async () => new Response(client,
  { headers: { "Content-Type": "text/javascript" } }) } });
assert.equal(served.status, 200);
const transformed = await served.text();
const mapName = homepage.MAP_NAME;
let expectedClient = client.replace(`"assets/${mapName}"`, `"${homepage.UI_PREFIX.slice(1)}${mapName}"`);
for (const [before, after] of manifest.copyUpdates) {
  assert.ok(client.includes(before), `Pinned disclosure anchor exists: ${before.slice(0, 70)}`);
  expectedClient = expectedClient.replace(before, after);
}
assert.equal(transformed, expectedClient);
assert.ok(!/Google Gemini|Gemini context|unpaid-tier content|free-tier requests/u.test(transformed));
for (const marker of ["hypha-voice-console__fax-frame", "hypha-voice-console__fax-image",
  "statement-clock__cipher-stream", "statement-clock__cipher-stream-label", "6/6 Plates Used (24h)",
  "Expose Latent Plate", "Decrypting Fax to Hypha…", "data:image/svg+xml", "era-v2"]) {
  assert.ok(client.includes(marker));
  assert.equal(transformed.split(marker).length, client.split(marker).length, `Preserved UI marker: ${marker}`);
}
astFor(transformed);
cases += 1;
console.log(`Live image integration validation passed (${cases} scenarios; 5 unchanged modules; exact fax/overlay preservation; no live API requests).`);
