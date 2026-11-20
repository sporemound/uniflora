import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";
import { parse } from "acorn";

const [argument, ...extra] = process.argv.slice(2);
assert.ok(argument && !extra.length,
  "Usage: node tools/validate_live_chat_delivery.mjs <patched-module-dir>");
const directory = resolve(argument);
const manifest = JSON.parse(await readFile(`${directory}.manifest.json`, "utf8"));
const sha256 = (value) => createHash("sha256").update(value).digest("hex");
assert.equal(manifest.modules.length, 7);
assert.equal(manifest.edits.length, 2);
assert.deepEqual((await readdir(directory)).sort(), manifest.modules.map(({ name }) => name).sort());
for (const { name, baselineSha256, sha256: expected, changed } of manifest.modules) {
  const bytes = await readFile(resolve(directory, name));
  const original = await readFile(resolve(manifest.inputDirectory, name));
  assert.equal(sha256(bytes), expected);
  assert.equal(sha256(original), baselineSha256);
  if (!changed) assert.equal(bytes.compare(original), 0, `${name} must stay byte-identical`);
}
const source = await readFile(resolve(directory, "preview.js"), "utf8");
const original = await readFile(resolve(manifest.inputDirectory, "preview.js"), "utf8");
let reapplied = original;
for (const { start, end, before, after } of manifest.edits.slice().reverse()) {
  assert.equal(original.slice(start, end), before);
  reapplied = reapplied.slice(0, start) + after + reapplied.slice(end);
}
assert.equal(reapplied, source, "Only the two targeted functions may change");
const functions = (text) => new Map(parse(text, { ecmaVersion: "latest", sourceType: "module" }).body
  .filter((node) => node.type === "FunctionDeclaration" && node.id)
  .map((node) => [node.id.name, text.slice(node.start, node.end)]));
const baselineFunctions = functions(original);
const patchedFunctions = functions(source);
for (const [name, text] of baselineFunctions) {
  if (!["handlePreviewChat", "requestOpenAI"].includes(name)) assert.equal(patchedFunctions.get(name), text);
}
// Hooks exist only in this in-memory test module, never in deployment output.
const testingSource = `${source}\nexport { handlePreviewChat };\nexport function installDeliveryTestHooks(game, voice) { availableHyphaGameActions = game; synthesizePreviewVoice = voice; }\n`;
const live = await import(`data:text/javascript;base64,${Buffer.from(testingSource).toString("base64")}`);
const origin = "https://uniflora.garden";
const key = "server-only-key-never-log";
const question = "Please compare the public signal";
const NOTICE = "Connection notice: Your message was saved, but Hypha cannot reply right now.";
const CREDIT_NOTICE = "Connection notice: Hypha cannot reply because its API credits are unavailable. Your message was saved.";
const complete = (text) => ({ status: "completed", output: [{ type: "message", role: "assistant",
  status: "completed", content: [{ type: "output_text", text }] }] });

function fixture() {
  const events = [];
  const requests = new Map();
  const messages = new Map();
  const proposals = [];
  const chatDb = {
    prepare(sql) {
      return { sql, values: [], bind(...values) { this.values = values; return this; },
        async first() {
          if (sql.includes("FROM hypha_chat_requests")) return requests.get(this.values[0]);
          throw new Error(`Unexpected query: ${sql}`);
        },
        async all() {
          if (sql.includes("SELECT sender_type, content_text")) {
            events.push("history");
            return { results: [{ sender_type: "hypha", content_text: "An earlier public reply" }] };
          }
          if (sql.includes("FROM hypha_chat_messages")) return { results: [...messages.values()]
            .filter((row) => row.request_id === this.values[0]) };
          throw new Error(`Unexpected query: ${sql}`);
        },
        async run() {
          const v = this.values;
          if (sql.includes("INSERT INTO preview_chat_quota")) events.push("quota");
          else if (sql.includes("UPDATE hypha_chat_requests SET status = 'processing'")) {
            events.push("claim"); requests.get(v[1]).status = "processing";
          } else if (sql.includes("UPDATE hypha_chat_messages SET delivery_status = 'processing'")) {
            messages.get(v[0]).delivery_status = "processing";
          } else if (sql.includes("INSERT INTO hypha_game_action_proposals")) {
            events.push("proposal"); proposals.push({ command: v[5], status: "pending" });
          } else if (sql.includes("INSERT INTO hypha_chat_messages")) {
            events.push("chat-only");
            messages.set(v[0], { message_id: v[0], request_id: v[1], environment: v[2], stream_id: v[3],
              sender_type: "participant", participant_id: v[4], working_name: v[5], content_text: v[6],
              delivery_status: "complete", created_at: v[7], completed_at: v[8], audio_available: 0 });
          } else throw new Error(`Unexpected run: ${sql}`);
          return { success: true, meta: { changes: 1 } };
        } };
    },
    async batch(statements) {
      const first = statements[0];
      const v = first.values;
      if (first.sql.includes("INSERT INTO hypha_chat_requests")) {
        events.push("persist");
        requests.set(v[0], { request_id: v[0], environment: v[4], stream_id: v[5], status: "pending",
          participant_message_id: v[7], hypha_message_id: v[8] });
        const p = statements[1].values;
        messages.set(p[0], { message_id: p[0], request_id: p[1], environment: p[2], stream_id: p[3],
          sender_type: "participant", participant_id: p[4], working_name: p[5], content_text: p[6],
          delivery_status: "complete", audio_available: 0, created_at: p[7], completed_at: p[8] });
        const h = statements[2].values;
        messages.set(h[0], { message_id: h[0], request_id: h[1], environment: h[2], stream_id: h[3],
          sender_type: "hypha", content_text: "", delivery_status: "pending", audio_available: 0,
          created_at: h[4], completed_at: null });
      } else if (first.sql.includes("UPDATE hypha_chat_messages")) {
        events.push("complete");
        Object.assign(messages.get(v[4]), { content_text: v[0], delivery_status: v[1], completed_at: v[3] });
        const last = statements.at(-1).values;
        requests.get(last[2]).status = last[0];
      } else throw new Error("Unexpected batch");
      return statements.map(() => ({ success: true, meta: { changes: 1 } }));
    },
  };
  const env = { APP_ORIGIN: origin, HYPHA_CHAT_PROVIDER: "openai", OPENAI_API_KEY: key,
    OPENAI_PRIVACY_ACKNOWLEDGED: "true", CHAT_DB: chatDb,
    PUBLIC_DB: { prepare(sql) { return { bind() { return this; }, async first() {
      if (sql.includes("FROM activity_sessions")) return { participant_id: "private-id",
        display_name: "Private Name", auth_provider: "email", expires_at: Math.floor(Date.now() / 1000) + 600 };
      if (sql.includes("FROM web_role_release_control")) return { handle: "Investigator", role_id: "field_observer" };
      return null;
    } }; } },
    ASSETS: { async fetch() { return Response.json({ positionTitle: "Public case", nextRequirement: "Observe" }); } },
  };
  return { env, events, requests, messages, proposals };
}
const request = (replyMode = "hypha") => new Request(`${origin}/api/hypha-chat`, { method: "POST",
  headers: { Origin: origin, "Content-Type": "application/json", Cookie: `__Host-mi_session=${"a".repeat(64)}` },
  body: JSON.stringify({ message: question, replyMode, albuquerqueMode: true }) });
const originalFetch = globalThis.fetch;
const originalWarn = console.warn;
const warnings = [];
console.warn = (...values) => warnings.push(values);

try {
  const cases = [
    { name: "bad-key", upstream: () => Response.json({ error: { code: "invalid_api_key", message: key } }, { status: 401 }),
      code: "chat_credentials_rejected", notice: "Connection notice: Hypha's API credentials were rejected. Your message was saved." },
    { name: "credit", upstream: () => Response.json({ error: { code: "insufficient_quota", message: key } }, { status: 429 }),
      code: "chat_credit_exhausted", notice: CREDIT_NOTICE },
    { name: "model", upstream: () => Response.json({ error: { code: "model_not_found", message: key } }, { status: 404 }),
      code: "chat_model_unavailable", notice: "Connection notice: Hypha's AI model is unavailable. Your message was saved." },
    { name: "request", upstream: () => Response.json({ error: { code: "unsupported_parameter", message: key } }, { status: 400 }),
      code: "chat_request_rejected", notice: "Connection notice: Hypha's AI service rejected this request. Your message was saved." },
    { name: "rate", upstream: () => Response.json({ error: { code: "rate_limit_exceeded", message: key } }, { status: 429 }),
      code: "chat_provider_rate_limited", notice: "Connection notice: Hypha's AI service is busy. Your message was saved. Please try again shortly." },
    { name: "timeout", upstream: () => { throw new DOMException("Private network detail", "AbortError"); } },
    { name: "incomplete", upstream: () => Response.json({ ...complete("partial"), status: "incomplete" }) },
    { name: "unconfigured", overrides: { OPENAI_API_KEY: undefined }, noNetwork: true },
    { name: "game-context-failure", gameFails: true, noNetwork: true },
  ];
  for (const scenario of cases) {
    const f = fixture();
    let modelCalls = 0;
    let voiceCalls = 0;
    let scheduled = 0;
    live.installDeliveryTestHooks(async () => {
      f.events.push("game");
      assert.ok(f.events.includes("persist"), "Game-context lookup follows saved messages");
      if (scenario.gameFails) throw new Error("private game issue");
      return { sequence: 1, suggestions: [{ command: "compare_signal", label: "Compare" }] };
    }, async () => { voiceCalls += 1; return null; });
    globalThis.fetch = async (url) => {
      assert.equal(url, "https://api.openai.com/v1/responses");
      f.events.push("inference"); modelCalls += 1;
      assert.ok(f.events.indexOf("persist") < f.events.indexOf("inference"));
      return scenario.upstream();
    };
    const response = await live.handlePreviewChat(request(), { ...f.env, ...scenario.overrides }, () => { scheduled += 1; });
    assert.equal(response.status, 201, scenario.name);
    const body = await response.json();
    assert.equal(body.messages.length, 2);
    assert.equal(body.messages[0].senderType, "participant");
    assert.equal(body.messages[0].text, question);
    assert.equal(body.messages[0].status, "complete");
    assert.equal(body.messages[1].senderType, "hypha");
    assert.equal(body.messages[1].status, "failed");
    assert.equal(body.messages[1].text, scenario.notice || NOTICE);
    assert.deepEqual(body.replyError, { code: scenario.code || "chat_unavailable", status: 503 });
    assert.equal(body.gameActionProposal, null);
    assert.equal(f.proposals.length, 0);
    assert.equal(voiceCalls, 0);
    assert.equal(scheduled, 0);
    assert.ok(f.events.indexOf("history") < f.events.indexOf("persist"));
    assert.equal(modelCalls, scenario.noNetwork ? 0 : 1, "No retries or provider fallback");
    assert.equal(JSON.stringify(body).includes(key), false);
  }
  const serializedWarnings = JSON.stringify(warnings);
  for (const privateValue of [key, question, "private-id", "Private Name", "Private network detail"]) {
    assert.equal(serializedWarnings.includes(privateValue), false, "Logs must contain no private values");
  }
  assert.ok(warnings.some(([, detail]) => detail?.status === 429 && detail?.code === "insufficient_quota"));

  const f = fixture();
  let voiceCalls = 0;
  const scheduled = [];
  live.installDeliveryTestHooks(async () => ({ sequence: 7,
    suggestions: [{ command: "compare_signal", label: "Compare the signal" }] }),
  async () => { voiceCalls += 1; return null; });
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "https://api.openai.com/v1/responses");
    const body = JSON.parse(options.body);
    assert.ok(f.events.includes("persist"));
    assert.match(body.instructions, /player must press Confirm/u);
    assert.match(body.instructions, /GAME_SUGGESTIONS:.*compare_signal/u);
    return Response.json(complete(JSON.stringify({ reply: "Awaiting your confirmation", actionIndex: 0 })));
  };
  const success = await live.handlePreviewChat(request(), f.env, (promise) => scheduled.push(promise));
  const successfulBody = await success.json();
  assert.equal(success.status, 201);
  assert.equal(successfulBody.messages[1].status, "complete");
  assert.equal(successfulBody.replyError, null);
  assert.equal(successfulBody.gameActionProposal.command, "compare_signal");
  assert.deepEqual(f.proposals, [{ command: "compare_signal", status: "pending" }],
    "Success only proposes an action; it never executes it");
  await Promise.all(scheduled);
  assert.equal(voiceCalls, 1);

  const chatOnly = fixture();
  globalThis.fetch = async () => { throw new Error("Chat-only must not call a model"); };
  const ordinary = await live.handlePreviewChat(request("chat_only"), { ...chatOnly.env,
    OPENAI_API_KEY: undefined });
  assert.equal(ordinary.status, 201);
  const ordinaryBody = await ordinary.json();
  assert.equal(ordinaryBody.messages.length, 1);
  assert.equal(ordinaryBody.messages[0].text, question);
  assert.equal(ordinaryBody.gameActionProposal, null);
} finally {
  globalThis.fetch = originalFetch;
  console.warn = originalWarn;
}

console.log("Live chat save-before-inference, persisted failure notices, safe diagnostics, and success/action/audio checks passed.");
