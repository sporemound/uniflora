import { HttpError } from "./errors";

const BASE_HEADERS: Record<string, string> = {
  "Cache-Control": "no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
};

export function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value, null, 2), {
    status,
    headers: {
      ...BASE_HEADERS,
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}

export function errorResponse(error: unknown): Response {
  if (error instanceof HttpError) {
    return jsonResponse(
      {
        error: error.code,
        detail: error.message,
      },
      error.status,
    );
  }

  console.error(error);
  return jsonResponse(
    {
      error: "internal_error",
      detail: "The Activity service could not complete the request.",
    },
    500,
  );
}

export function methodNotAllowed(allowed: string[]): Response {
  const response = jsonResponse({ error: "method_not_allowed" }, 405);
  response.headers.set("Allow", allowed.join(", "));
  return response;
}

export function artifactResponse(
  body: ReadableStream<Uint8Array> | null,
  options: {
    contentType: string;
    byteLength: number;
    etag: string;
    sha256: string;
    filename: string;
  },
): Response {
  return new Response(body, {
    headers: {
      "Cache-Control": "public, max-age=31536000, immutable",
      "Content-Disposition": `inline; filename="${options.filename}"`,
      "Content-Length": String(options.byteLength),
      "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:",
      "Content-Type": options.contentType,
      ETag: options.etag,
      "Referrer-Policy": "no-referrer",
      "X-Content-SHA256": options.sha256,
      "X-Content-Type-Options": "nosniff",
    },
  });
}
