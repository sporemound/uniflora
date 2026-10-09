import assert from "node:assert/strict";
import { build } from "esbuild";

async function bundledModule(entry) {
  const result = await build({
    entryPoints: [entry],
    bundle: true,
    format: "esm",
    platform: "neutral",
    write: false,
  });
  const source = Buffer.from(result.outputFiles[0].contents).toString("base64");
  return import(`data:text/javascript;base64,${source}`);
}

const { transformAlbuquerqueMarkdown } = await bundledModule("worker/lib/preview-albuquerque.ts");
assert.equal(transformAlbuquerqueMarkdown("cat"), "caAlbuquerquet");
assert.equal(transformAlbuquerqueMarkdown("GO"), "GOAlbuquerque");
assert.equal(transformAlbuquerqueMarkdown("book"),
  "boAlbuquerqueoAlbuquerquek");
assert.equal(transformAlbuquerqueMarkdown("[hello](https://example.com/path)"),
  "[heAlbuquerquelloAlbuquerque](https://example.com/path)");
assert.equal(transformAlbuquerqueMarkdown("`code` and https://example.com/path"),
  "`code` aAlbuquerquend https://example.com/path");
assert.equal(transformAlbuquerqueMarkdown("```js\nhello\n```\ncat"),
  "```js\nhello\n```\ncaAlbuquerquet");

const { interactionText } = await bundledModule("worker/lib/preview-chat.ts");
const modelOutput = { steps: [{ type: "model_output", content: [{ type: "text", text: "Hello from Hypha" }] }] };
assert.equal(interactionText(modelOutput), "Hello from Hypha");
assert.equal(interactionText({ interaction: modelOutput }), "Hello from Hypha");
assert.equal(interactionText({ steps: [{ type: "thought", content: [{ text: "private" }] }] }), "");

const { readWebSession } = await bundledModule("worker/lib/magic-link-auth.ts");
const statements = [];
const session = await readWebSession(new Request("https://example.com/api/session", {
  headers: { Cookie: `__Host-mi_session=${"a".repeat(64)}` },
}), {
  APP_ORIGIN: "https://example.com",
  PUBLIC_DB: {
    prepare(sql) {
      statements.push(sql);
      return {
        bind() { return this; },
        async first() {
          return { participant_id: "participant_123", display_name: "Investigator 123",
            expires_at: Math.floor(Date.now() / 1000) + 600 };
        },
      };
    },
  },
});
assert.equal(session?.participant.participantId, "participant_123");
assert.equal(statements.length, 1, "session polling must not write to D1");
assert.match(statements[0], /^SELECT /u);

const { default: previewWorker } = await bundledModule("worker/preview.ts");
const origin = "https://preview.example.com";
const env = {
  APP_ORIGIN: origin,
  ASSETS: { fetch: async () => new Response("{}", { headers: { "Content-Type": "application/json" } }) },
  PUBLIC_DB: {},
  CHAT_DB: {},
};
const health = await previewWorker.fetch(new Request(`${origin}/api/health`), env);
assert.deepEqual(await health.json(), {
  status: "preview", emailReady: false, chatReady: false,
  chatReadReady: false, demoReady: false,
  emailSchemaReady: false, chatSchemaReady: false, gameActionsReady: false,
});
const unsignedChat = await previewWorker.fetch(new Request(`${origin}/api/hypha-chat`, {
  method: "POST", headers: { Origin: origin, "Content-Type": "application/json" },
  body: JSON.stringify({ message: "Hello" }),
}), { ...env, GEMINI_API_KEY: "test-key" });
assert.equal(unsignedChat.status, 401, "chat must require an email session");
const unsignedHistory = await previewWorker.fetch(new Request(`${origin}/api/hypha-chat`), {
  ...env, GEMINI_API_KEY: "test-key",
});
assert.equal(unsignedHistory.status, 503, "chat history waits for its own database schema");
const transcriptQueries = [];
const publicHistory = await previewWorker.fetch(new Request(`${origin}/api/hypha-chat?limit=5`), {
  ...env,
  PUBLIC_DB: {},
  CHAT_DB: {
    prepare(sql) {
      transcriptQueries.push(sql);
      if (sql.includes("sqlite_master")) return {
        bind() { return this; },
        async all() { return { results: [{ name: "hypha_chat_messages" }] }; },
      };
      return {
        bind() { return this; },
        async all() { return { results: [{
          row_id: 1, message_id: "message-1", request_id: "request-1",
          environment: "live", stream_id: "web-preview", sender_type: "participant",
          participant_id: "participant_email-derived-id", working_name: "Investigator",
          content_text: "A public question", delivery_status: "complete",
          audio_available: 0, created_at: 1, completed_at: 1,
        }] }; },
      };
    },
  },
});
assert.equal(publicHistory.status, 200, "a guest can read the shared transcript");
const publicHistoryBody = await publicHistory.json();
assert.equal(publicHistoryBody.messages[0].text, "A public question");
assert.equal(publicHistoryBody.messages[0].participantId, null,
  "public transcript must not expose an email-derived ID");
assert.equal(publicHistory.headers.get("Cache-Control"), "no-store");
assert.equal(transcriptQueries.length, 2, "public history reads only its chat database");
const publicHistoryHealth = await previewWorker.fetch(new Request(`${origin}/api/health`), {
  ...env,
  PUBLIC_DB: {},
  CHAT_DB: {
    prepare(sql) {
      if (!sql.includes("sqlite_master")) throw new Error("unexpected query");
      return {
        bind() { return this; },
        async all() { return { results: [{ name: "hypha_chat_messages" }] }; },
      };
    },
  },
});
const publicHealth = await publicHistoryHealth.json();
assert.equal(publicHealth.chatReadReady, true);
assert.equal(publicHealth.chatReady, false,
  "public read readiness does not imply that anyone can post");
const unconfiguredEmail = await previewWorker.fetch(new Request(`${origin}/api/auth/magic-link/request`, {
  method: "POST", headers: { Origin: origin, "Content-Type": "application/json" },
  body: JSON.stringify({ email: "player@example.com" }),
}), env);
assert.equal(unconfiguredEmail.status, 503);
const quotaStatements = [];
const configuredEmailEnv = {
  ...env,
  RESEND_API_KEY: "local-test-key",
  MAGIC_LINK_FROM_EMAIL: "sign-in@example.com",
  ACTIVITY_IDENTITY_SECRET: "identity-secret-with-at-least-32-chars",
  PUBLIC_DB: {
    prepare(sql) {
      if (sql.includes("sqlite_master")) {
        return {
          bind() { return this; },
          async all() { return { results: [
            "activity_sessions", "web_magic_links", "web_magic_link_cooldowns",
            "preview_magic_link_quota",
          ].map((name) => ({ name })) }; },
        };
      }
      quotaStatements.push(sql);
      return { bind() { return this; }, async run() { return { meta: { changes: 0 } }; } };
    },
  },
};
const invalidEmail = await previewWorker.fetch(new Request(`${origin}/api/auth/magic-link/request`, {
  method: "POST", headers: { Origin: origin, "Content-Type": "application/json" },
  body: JSON.stringify({ email: "not-an-email" }),
}), configuredEmailEnv);
assert.equal(invalidEmail.status, 202);
assert.equal(quotaStatements.length, 0, "invalid addresses must not consume mail quota");
const cappedEmail = await previewWorker.fetch(new Request(`${origin}/api/auth/magic-link/request`, {
  method: "POST", headers: { Origin: origin, "Content-Type": "application/json",
    "CF-Connecting-IP": "203.0.113.7" },
  body: JSON.stringify({ email: "player@example.com" }),
}), configuredEmailEnv);
assert.equal(cappedEmail.status, 202, "mail quota must keep the generic response");
assert.equal(quotaStatements.length, 1, "capped IP must not charge global quota or send mail");
const missingSchemaHealth = await previewWorker.fetch(new Request(`${origin}/api/health`), {
  ...configuredEmailEnv, PUBLIC_DB: {}, CHAT_DB: {}, GEMINI_API_KEY: "test-key",
});
assert.equal((await missingSchemaHealth.json()).chatReady, false,
  "configured bindings without migrations must not claim chat readiness");
const missingSchemaSession = await previewWorker.fetch(new Request(`${origin}/api/session`), {
  ...configuredEmailEnv, PUBLIC_DB: {},
});
assert.equal(missingSchemaSession.status, 503,
  "session route must report unavailable schema before reading a cookie");
const missingSchemaChat = await previewWorker.fetch(new Request(`${origin}/api/hypha-chat`, {
  headers: { Cookie: `__Host-mi_session=${"a".repeat(64)}` },
}), { ...configuredEmailEnv, PUBLIC_DB: {}, CHAT_DB: {}, GEMINI_API_KEY: "test-key" });
assert.equal(missingSchemaChat.status, 503,
  "signed-in chat route must report unavailable schema");
const gameWrite = await previewWorker.fetch(new Request(`${origin}/api/game/command`, { method: "POST" }), env);
assert.equal(gameWrite.status, 401, "preview game actions require email sign-in");

console.log("Preview chat/auth boundary and Albuquerque rendering checks passed.");
