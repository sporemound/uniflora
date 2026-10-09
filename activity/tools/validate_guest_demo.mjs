import assert from "node:assert/strict";
import { build } from "esbuild";

const bundled = await build({
  entryPoints: ["worker/preview.ts"], bundle: true, format: "esm",
  platform: "neutral", write: false,
});
const source = Buffer.from(bundled.outputFiles[0].contents).toString("base64");
const { default: previewWorker } = await import(`data:text/javascript;base64,${source}`);
const origin = "https://preview.example.com";
let modelCalls = 0;
let assetCalls = 0;
let modelReply = "cat";
const rateKeys = [];
const globalKeys = [];
const storedMessages = [];
let schemaReady = true;
let failBatch = false;
const chatDb = {
  prepare(sql) {
    return {
      sql,
      values: [],
      bind(...values) { this.values = values; return this; },
      async first() {
        if (sql.includes("sqlite_master")) {
          return schemaReady ? { name: "hypha_chat_messages" } : null;
        }
        if (sql.includes("SELECT row_id FROM hypha_chat_messages")) {
          const row = storedMessages.find((message) => message.message_id === this.values[0]);
          return row ? { row_id: row.row_id } : null;
        }
        throw new Error(`Unexpected D1 first query: ${sql}`);
      },
      async all() {
        if (sql.includes("sqlite_master")) {
          return { success: true, results: schemaReady ? [{ name: "hypha_chat_messages" }] : [] };
        }
        if (sql.includes("FROM hypha_chat_messages")) {
          return { success: true, results: storedMessages.slice().reverse() };
        }
        throw new Error(`Unexpected D1 all query: ${sql}`);
      },
    };
  },
  async batch(statements) {
    assert.equal(statements.length, 2, "guest question and reply must commit in one batch");
    if (failBatch) throw new Error("D1 unavailable");
    const [question, reply] = statements;
    assert.match(question.sql, /INSERT INTO hypha_chat_messages/u);
    assert.match(reply.sql, /INSERT INTO hypha_chat_messages/u);
    assert.match(question.sql, /'live', 'web-preview', 'participant'/u);
    assert.match(reply.sql, /'live', 'web-preview', 'hypha'/u);
    const [questionId, requestId, participantId, questionText, askedAt] = question.values;
    const [replyId, replyRequestId, replyText, answeredAt] = reply.values;
    assert.equal(replyRequestId, requestId);
    assert.match(participantId, /^guest:[0-9a-f-]{36}$/u);
    assert.notEqual(participantId, "203.0.113.1");
    assert.ok(Number.isInteger(askedAt) && Number.isInteger(answeredAt));
    storedMessages.push({ row_id: storedMessages.length + 1, message_id: questionId,
      request_id: requestId, environment: "live", stream_id: "web-preview",
      sender_type: "participant", participant_id: participantId, working_name: "Guest",
      content_text: questionText, delivery_status: "complete", audio_available: 0,
      created_at: askedAt, completed_at: askedAt });
    storedMessages.push({ row_id: storedMessages.length + 1, message_id: replyId,
      request_id: requestId, environment: "live", stream_id: "web-preview",
      sender_type: "hypha", participant_id: null, working_name: null,
      content_text: replyText, delivery_status: "complete", audio_available: 0,
      created_at: answeredAt, completed_at: answeredAt });
    return [{ success: true, meta: { changes: 1 } }, { success: true, meta: { changes: 1 } }];
  },
};
const mockEnv = {
  APP_ORIGIN: origin,
  ACTIVITY_IDENTITY_SECRET: "guest-demo-test-secret-of-at-least-32-characters",
  DEMO_CHAT_ENABLED: "true",
  GEMINI_API_KEY: "server-only-test-key",
  CHAT_DB: chatDb,
  ASSETS: {
    async fetch(request) {
      assetCalls += 1;
      assert.equal(new URL(request.url).pathname, "/preview-live-state.json");
      return Response.json({ positionTitle: "The First Return", nextRequirement: "Observe",
        evidence: [{ name: "Public signal", status: "captured" }] });
    },
  },
  DEMO_IP_RATE_LIMIT: { async limit({ key }) { rateKeys.push(key); return { success: rateKeys.length <= 2 }; } },
  DEMO_GLOBAL_RATE_LIMIT: { async limit({ key }) { globalKeys.push(key); return { success: true }; } },
};
const originalFetch = globalThis.fetch;
globalThis.fetch = async (url, options) => {
  modelCalls += 1;
  assert.equal(url, "https://generativelanguage.googleapis.com/v1beta/interactions");
  assert.equal(options.headers["x-goog-api-key"], "server-only-test-key");
  const body = JSON.parse(options.body);
  assert.equal(body.store, false);
  assert.equal(body.model, "gemini-3.5-flash-lite");
  assert.equal(body.generation_config.max_output_tokens, 350);
  assert.equal(body.generation_config.thinking_level, "low");
  assert.match(body.system_instruction, /The First Return/u);
  assert.doesNotMatch(body.input, /RECENT_SHARED_HISTORY/u);
  return Response.json({ steps: [{ type: "model_output", content: [{ text: modelReply }] }] });
};
function request(body, headers = {}) {
  return new Request(`${origin}/api/hypha-demo`, {
    method: "POST",
    headers: { Origin: origin, "Content-Type": "application/json",
      "CF-Connecting-IP": "203.0.113.1", ...headers },
    body: JSON.stringify(body),
  });
}

try {
  const health = await previewWorker.fetch(new Request(`${origin}/api/health`), {
    ...mockEnv, PUBLIC_DB: {},
  });
  const readiness = await health.json();
  assert.equal(readiness.demoReady, true, "guest demo needs public log but no mail sender");
  assert.equal(readiness.chatReady, false);
  assert.equal((await previewWorker.fetch(new Request(`${origin}/api/hypha-demo`), mockEnv)).status, 405);
  assert.equal((await previewWorker.fetch(request({ message: "Hello" }, { Origin: "https://evil.example" }), mockEnv)).status, 403);
  assert.equal((await previewWorker.fetch(request({ message: "Hello", secret: "do not send" }), mockEnv)).status, 400);
  assert.equal((await previewWorker.fetch(request({ message: "Hello", albuquerqueMode: "yes" }), mockEnv)).status, 400);
  assert.equal((await previewWorker.fetch(request({ message: "x".repeat(501) }), mockEnv)).status, 400);
  assert.equal((await previewWorker.fetch(request({ message: "x".repeat(4096) }), mockEnv)).status, 413);
  assert.equal((await previewWorker.fetch(request({ message: "Hello" }), {
    ...mockEnv, DEMO_CHAT_ENABLED: "false",
  })).status, 503);
  assert.equal((await previewWorker.fetch(request({ message: "Hello" }), {
    ...mockEnv, DEMO_GLOBAL_RATE_LIMIT: undefined,
  })).status, 503, "missing rate limiter must fail closed");
  assert.equal((await previewWorker.fetch(request({ message: "Hello" }), {
    ...mockEnv, CHAT_DB: undefined,
  })).status, 503, "missing public log must fail closed");
  schemaReady = false;
  assert.equal((await previewWorker.fetch(request({ message: "Hello" }), {
    ...mockEnv, DEMO_IP_RATE_LIMIT: { async limit() { return { success: true }; } },
  })).status, 503, "missing chat table must fail before Gemini");
  schemaReady = true;
  assert.equal(modelCalls, 0, "invalid or unconfigured requests must not call Gemini");

  const plain = await previewWorker.fetch(request({ message: "What is the public signal?" }), mockEnv);
  assert.equal(plain.status, 200);
  assert.deepEqual(await plain.json(), { reply: "cat", albuquerqueMode: false });
  assert.equal(plain.headers.get("Cache-Control"), "no-store");
  const transformed = await previewWorker.fetch(request({ message: "enable Albuquerque mode" }), mockEnv);
  assert.equal(transformed.status, 200);
  assert.deepEqual(await transformed.json(), { reply: "caAlbuquerquet", albuquerqueMode: true });
  assert.equal(storedMessages.length, 4);
  assert.deepEqual(storedMessages.map((item) => item.content_text), [
    "What is the public signal?", "cat", "enable Albuquerque mode", "caAlbuquerquet",
  ]);
  assert.notEqual(storedMessages[0].participant_id, storedMessages[2].participant_id,
    "guest identity must change for each question");
  const publicLog = await previewWorker.fetch(new Request(`${origin}/api/hypha-chat?limit=50`), {
    ...mockEnv, PUBLIC_DB: {},
  });
  assert.equal(publicLog.status, 200);
  const visible = await publicLog.json();
  assert.deepEqual(visible.messages.map((item) => item.text), storedMessages.map((item) => item.content_text),
    "signed-out visitors must see both guest questions and replies");
  assert.ok(visible.messages.every((item) => item.participantId === null),
    "public response must not expose ephemeral identity");
  assert.equal(rateKeys.length, 2);
  assert.ok(rateKeys.every((key) => /^[0-9a-f]{64}$/u.test(key)), "rate keys must hide raw IPs");
  assert.deepEqual(globalKeys, ["hypha-demo", "hypha-demo", "hypha-demo"]);
  assert.equal(assetCalls, 2, "each answer uses the curated public snapshot once");
  const limited = await previewWorker.fetch(request({ message: "One more?" }), mockEnv);
  assert.equal(limited.status, 429);
  assert.equal(modelCalls, 2, "rate-limited request must not reach Gemini");
  const globalLimited = await previewWorker.fetch(request({ message: "Hello" }, {
    "CF-Connecting-IP": "203.0.113.2",
  }), { ...mockEnv,
    DEMO_IP_RATE_LIMIT: { async limit() { return { success: true }; } },
    DEMO_GLOBAL_RATE_LIMIT: { async limit() { return { success: false }; } },
  });
  assert.equal(globalLimited.status, 429);
  assert.equal(modelCalls, 2);
  modelReply = "e".repeat(2000);
  const longReply = await previewWorker.fetch(request({ message: "Answer in Albuquerque mode", albuquerqueMode: true }), {
    ...mockEnv,
    DEMO_IP_RATE_LIMIT: { async limit() { return { success: true }; } },
  });
  assert.equal(longReply.status, 200);
  assert.ok((await longReply.json()).reply.length <= 1000,
    "Albuquerque expansion must stay within the guest response cap");
  assert.ok(storedMessages.at(-1).content_text.length <= 1000,
    "the public log must store the bounded reply actually shown");
  const previousStored = storedMessages.length;
  failBatch = true;
  const unlogged = await previewWorker.fetch(request({ message: "Will this be saved?" }), {
    ...mockEnv,
    DEMO_IP_RATE_LIMIT: { async limit() { return { success: true }; } },
  });
  assert.equal(unlogged.status, 503, "failed public log must not return a successful reply");
  assert.equal(storedMessages.length, previousStored, "failed batch must not publish half an exchange");
} finally {
  globalThis.fetch = originalFetch;
}

console.log("Public guest Hypha log, rate, origin, persistence, and payload checks passed.");
