import assert from "node:assert/strict";
import { build } from "esbuild";

const bundled = await build({
  entryPoints: ["worker/lib/low-cost-image.ts"], bundle: true,
  format: "esm", platform: "neutral", write: false,
});
const source = Buffer.from(bundled.outputFiles[0].contents).toString("base64");
const { imageProviderConfigured, generateLowCostImage } = await import(`data:text/javascript;base64,${source}`);
const env = { OPENAI_API_KEY: " test-server-only-key ", OPENAI_PRIVACY_ACKNOWLEDGED: "true" };
const subjectDigest = "a".repeat(64);
// A small framing fixture: no real provider call is made by this validator.
const jpeg = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0, 2, 0xff, 0xd9]).toString("base64");
let calls = [];
let network = async () => Response.json({ data: [{ b64_json: jpeg }] });
const originalFetch = globalThis.fetch;
globalThis.fetch = async (...args) => { calls.push(args); return network(...args); };
let checks = 0;

async function fails(code, fn, expectedCalls = 1) {
  calls = [];
  await assert.rejects(fn, (error) => {
    assert.equal(error.code, code);
    assert.ok(!error.message.includes("PROVIDER_PRIVATE_PAYLOAD"));
    assert.ok(!error.message.includes(env.OPENAI_API_KEY.trim()));
    return true;
  });
  assert.equal(calls.length, expectedCalls, "no retries or fallbacks");
  checks += 1;
}

try {
  assert.equal(imageProviderConfigured(env), true);
  for (const changed of [
    { OPENAI_API_KEY: undefined }, { OPENAI_API_KEY: " " },
    { OPENAI_PRIVACY_ACKNOWLEDGED: undefined }, { OPENAI_PRIVACY_ACKNOWLEDGED: "false" },
  ]) {
    const invalid = { ...env, ...changed };
    assert.equal(imageProviderConfigured(invalid), false);
    await fails("image_credentials_rejected", () => generateLowCostImage(invalid, "A quiet room"), 0);
  }
  calls = [];
  const image = await generateLowCostImage(env, " A quiet room ", subjectDigest);
  assert.deepEqual(image, { dataUrl: `data:image/jpeg;base64,${jpeg}`, modelUsed: "gpt-image-2.6-flare (high, era-v2)" });
  assert.equal(calls.length, 1);
  const [url, request] = calls[0];
  assert.equal(url, "https://api.openai.com/v1/images/generations");
  assert.equal(request.method, "POST");
  assert.equal(request.headers.Authorization, "Bearer test-server-only-key");
  assert.ok(request.signal instanceof AbortSignal);
  assert.deepEqual(JSON.parse(request.body), {
    model: "gpt-image-2.6-flare", prompt: "A quiet room", n: 1,
    size: "1536x864", quality: "high", output_format: "jpeg", output_compression: 100,
    moderation: "auto", safety_identifier: subjectDigest,
  });
  checks += 1;
  calls = [];
  await generateLowCostImage(env, "Room without an identifier");
  assert.equal(JSON.parse(calls[0][1].body).safety_identifier, undefined);
  checks += 1;

  for (const [status, code, expected] of [
    [401, "ignored", "image_credentials_rejected"], [403, "ignored", "image_credentials_rejected"],
    [429, "insufficient_quota", "image_credit_exhausted"],
    [429, "credit_balance_exhausted", "image_credit_exhausted"],
    [429, "rate_limit_exceeded", "image_rate_limited"],
    [400, "content_policy_violation", "image_request_rejected"],
    [422, "ignored", "image_request_rejected"], [404, "model_not_found", "image_model_unavailable"],
    [500, "ignored", "image_generation_unavailable"],
  ]) {
    network = async () => Response.json({ error: { code, message: "PROVIDER_PRIVATE_PAYLOAD" } }, { status });
    await fails(expected, () => generateLowCostImage(env, "A quiet room"));
  }
  network = async () => new Response("PROVIDER_PRIVATE_PAYLOAD", { status: 401 });
  await fails("image_credentials_rejected", () => generateLowCostImage(env, "A quiet room"));
  for (const payload of [
    {}, { refusal: "PROVIDER_PRIVATE_PAYLOAD" }, { data: [] }, { data: [{ b64_json: "" }] },
    { data: [{ b64_json: jpeg }, { b64_json: jpeg }] },
    { data: [{ b64_json: "invalid@@==" }] },
    { data: [{ b64_json: jpeg.slice(0, -1) }] },
    { data: [{ b64_json: Buffer.from("not a jpeg").toString("base64") }] },
    { data: [{ b64_json: Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0, 2]).toString("base64") }] },
    { data: [{ b64_json: Buffer.alloc(1_400_001).toString("base64") }] },
  ]) {
    network = async () => Response.json(payload);
    await fails("image_generation_unavailable", () => generateLowCostImage(env, "A quiet room"));
  }
  network = async () => new Response("not json");
  await fails("image_generation_unavailable", () => generateLowCostImage(env, "A quiet room"));
  network = async () => { throw new DOMException("PROVIDER_PRIVATE_PAYLOAD", "TimeoutError"); };
  await fails("image_generation_unavailable", () => generateLowCostImage(env, "A quiet room"));
  network = async () => { throw new Error("PROVIDER_PRIVATE_PAYLOAD"); };
  await fails("image_generation_unavailable", () => generateLowCostImage(env, "A quiet room"));
  network = async () => new Response("x", { headers: { "Content-Length": String(2 * 1024 * 1024 + 1) } });
  await fails("image_generation_unavailable", () => generateLowCostImage(env, "A quiet room"));
  network = async () => new Response("x".repeat(2 * 1024 * 1024 + 1));
  await fails("image_generation_unavailable", () => generateLowCostImage(env, "A quiet room"));
  for (const prompt of ["", "  ", "x".repeat(8193)]) {
    await fails("image_request_rejected", () => generateLowCostImage(env, prompt), 0);
  }
  await fails("image_request_rejected", () => generateLowCostImage(env, "A quiet room", "raw-participant-id"), 0);
  // Verify the largest permitted stored image remains within the byte limit.
  const largest = Buffer.alloc(1_400_000);
  largest.set([0xff, 0xd8, 0xff]); largest.set([0xff, 0xd9], largest.length - 2);
  network = async () => Response.json({ data: [{ b64_json: largest.toString("base64") }] });
  const result = await generateLowCostImage(env, "A quiet room");
  assert.equal(Buffer.from(result.dataUrl.split(",")[1], "base64").length, 1_400_000);
  checks += 1;
  console.log(`Low-cost image validation passed (${checks} checks; no live API requests).`);
} finally {
  globalThis.fetch = originalFetch;
}
