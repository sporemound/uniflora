/** One explicitly requested widescreen plate, preserving high image quality. */
import { HttpError } from "./errors";

export interface ImageProviderEnv {
  OPENAI_API_KEY?: string;
  OPENAI_PRIVACY_ACKNOWLEDGED?: string;
}

const IMAGE_ENDPOINT = "https://api.openai.com/v1/images/generations";
const IMAGE_MODEL = "gpt-image-2.6-flare";
const MAX_PROMPT_CHARACTERS = 8192;
// Leave room for the other fields in the existing D1 plate row.
const MAX_IMAGE_BYTES = 1_400_000;
const HYPHA_IMAGE_MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const MAX_BASE64_CHARACTERS = Math.ceil(MAX_IMAGE_BYTES / 3) * 4;

export function imageProviderConfigured(env: ImageProviderEnv): boolean {
  return Boolean(env.OPENAI_API_KEY?.trim()) &&
    env.OPENAI_PRIVACY_ACKNOWLEDGED?.trim().toLowerCase() === "true";
}

function imageUnavailable(): HttpError {
  return new HttpError(502, "image_generation_unavailable",
    "Image reconstruction did not complete. Your plate slot was not consumed.");
}

async function boundedImageResponse(response: Response): Promise<unknown> {
  const declared = Number(response.headers.get("Content-Length") ?? 0);
  if (declared > HYPHA_IMAGE_MAX_RESPONSE_BYTES || !response.body) throw imageUnavailable();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    for (;;) {
      const part = await reader.read();
      if (part.done) break;
      length += part.value.byteLength;
      if (length > HYPHA_IMAGE_MAX_RESPONSE_BYTES) {
        await reader.cancel();
        throw imageUnavailable();
      }
      chunks.push(part.value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try { return JSON.parse(new TextDecoder().decode(bytes)); }
  catch { throw imageUnavailable(); }
}

function imageServiceError(status: number, payload: unknown): HttpError {
  const error = payload && typeof payload === "object" && "error" in payload
    ? (payload as { error?: unknown }).error : null;
  const code = error && typeof error === "object" && "code" in error
    ? (error as { code?: unknown }).code : null;
  if (status === 401 || status === 403) {
    return new HttpError(503, "image_credentials_rejected",
      "Image reconstruction credentials are unavailable. Your plate slot was not consumed.");
  }
  if (status === 429 && (code === "insufficient_quota" || code === "credit_balance_exhausted")) {
    return new HttpError(503, "image_credit_exhausted",
      "Image reconstruction credits are unavailable. Your plate slot was not consumed.");
  }
  if (status === 429) {
    return new HttpError(429, "image_rate_limited",
      "The image service is busy. Your plate slot was not consumed. Try again later.");
  }
  if (status === 404) {
    return new HttpError(503, "image_model_unavailable",
      "The image model is unavailable. Your plate slot was not consumed.");
  }
  if (status === 400 || status === 422) {
    return new HttpError(502, "image_request_rejected",
      "The image service could not accept this reconstruction. Your plate slot was not consumed.");
  }
  return imageUnavailable();
}

/** Validate encoding, size and JPEG framing before persisting provider bytes. */
function jpegBase64(payload: unknown): string {
  if (!payload || typeof payload !== "object") throw imageUnavailable();
  const data = (payload as { data?: unknown }).data;
  if (!Array.isArray(data) || data.length !== 1 || !data[0] || typeof data[0] !== "object") {
    throw imageUnavailable();
  }
  const encoded = (data[0] as { b64_json?: unknown }).b64_json;
  if (typeof encoded !== "string" || encoded.length > MAX_BASE64_CHARACTERS ||
      !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/u.test(encoded)) {
    throw imageUnavailable();
  }
  let bytes: string;
  try { bytes = atob(encoded); }
  catch { throw imageUnavailable(); }
  if (bytes.length < 6 || bytes.length > MAX_IMAGE_BYTES || btoa(bytes) !== encoded ||
      bytes.charCodeAt(0) !== 0xff || bytes.charCodeAt(1) !== 0xd8 || bytes.charCodeAt(2) !== 0xff ||
      bytes.charCodeAt(bytes.length - 2) !== 0xff || bytes.charCodeAt(bytes.length - 1) !== 0xd9) {
    throw imageUnavailable();
  }
  return encoded;
}

export async function generateLowCostImage(
  env: ImageProviderEnv,
  prompt: string,
  safetyIdentifier?: string,
): Promise<{ dataUrl: string; modelUsed: string }> {
  if (!imageProviderConfigured(env)) {
    throw new HttpError(503, "image_credentials_rejected",
      "Image reconstruction is not configured. Your plate slot was not consumed.");
  }
  if (typeof prompt !== "string" || !prompt.trim() || prompt.length > MAX_PROMPT_CHARACTERS) {
    throw new HttpError(400, "image_request_rejected", "The reconstruction prompt is invalid.");
  }
  // Only a one-way subject digest may be forwarded, never an email or raw ID.
  if (safetyIdentifier !== undefined && !/^[0-9a-f]{64}$/u.test(safetyIdentifier)) {
    throw new HttpError(400, "image_request_rejected", "The reconstruction identifier is invalid.");
  }
  try {
    const response = await fetch(IMAGE_ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${env.OPENAI_API_KEY!.trim()}`,
      },
      body: JSON.stringify({
        model: IMAGE_MODEL,
        prompt: prompt.trim(),
        n: 1,
        size: "1536x864",
        quality: "high",
        output_format: "jpeg",
        output_compression: 100,
        moderation: "auto",
        ...(safetyIdentifier ? { safety_identifier: safetyIdentifier } : {}),
      }),
      signal: AbortSignal.timeout(150_000),
    });
    let payload: unknown;
    try { payload = await boundedImageResponse(response); }
    catch {
      if (!response.ok) throw imageServiceError(response.status, null);
      throw imageUnavailable();
    }
    if (!response.ok) throw imageServiceError(response.status, payload);
    return {
      dataUrl: `data:image/jpeg;base64,${jpegBase64(payload)}`,
      modelUsed: `${IMAGE_MODEL} (high, era-v2)`,
    };
  } catch (error) {
    // Never log or return provider response bodies, request text or credentials.
    if (error instanceof HttpError) throw error;
    throw imageUnavailable();
  }
}
