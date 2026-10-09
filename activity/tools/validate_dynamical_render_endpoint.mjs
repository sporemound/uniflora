import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { transformWithOxc } from "vite";

const ROOT = process.cwd();

async function transformedSource(relativePath) {
  const absolutePath = path.join(ROOT, relativePath);
  const source = await readFile(absolutePath, "utf8");
  return (await transformWithOxc(source, absolutePath)).code;
}

function moduleUrl(source) {
  return `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
}

const errorsUrl = moduleUrl(await transformedSource("worker/lib/errors.ts"));
const responsesUrl = moduleUrl(
  (await transformedSource("worker/lib/responses.ts"))
    .replace('from "./errors"', `from ${JSON.stringify(errorsUrl)}`),
);
const datasetsUrl = moduleUrl(
  await transformedSource("src/shared/dynamical-data.ts"),
);
const endpointSource = (await transformedSource(
  "worker/lib/dynamical-render-manifest.ts",
))
  .replace(
    'from "../../src/shared/dynamical-data"',
    `from ${JSON.stringify(datasetsUrl)}`,
  )
  .replace('from "./errors"', `from ${JSON.stringify(errorsUrl)}`)
  .replace('from "./responses"', `from ${JSON.stringify(responsesUrl)}`);
const { handleDynamicalRenderManifest } = await import(moduleUrl(endpointSource));

const datasetIds = [
  "dynamical-asos",
  "dynamical-gfs-analysis",
  "dynamical-hrrr-analysis",
  "dynamical-mrms-analysis",
  "dynamical-imerg-late",
];
const validTime = "2026-08-02T12:00:00.000Z";

function layer(datasetId) {
  return {
    schemaVersion: 1,
    datasetId,
    kind: "image",
    url: `/data/dynamical/${datasetId}.png`,
    coordinates: [[-120, 50], [-60, 50], [-60, 20], [-120, 20]],
    generatedAt: "2026-08-02T12:10:00.000Z",
    validTime,
    variable: "test_field",
    units: "%",
    attribution: "Test renderer",
    status: "ready",
  };
}

function manifest(overrides = {}) {
  return {
    schemaVersion: 1,
    generatedAt: "2026-08-02T12:10:00.000Z",
    layers: Object.fromEntries(datasetIds.map((datasetId) => [
      datasetId,
      layer(datasetId),
    ])),
    ...overrides,
  };
}

function environment(index = manifest(), options = {}) {
  const state = { assetRequests: [] };
  return {
    state,
    env: {
      ASSETS: {
        async fetch(request) {
          state.assetRequests.push(request);
          if (options.throwAssetError) throw new Error("asset failure");
          return new Response(
            options.assetBody ?? JSON.stringify(index),
            {
              status: options.assetStatus ?? 200,
              headers: {
                "Content-Type": options.contentType ?? "application/json",
              },
            },
          );
        },
      },
    },
  };
}

function request(search = "dataset=dynamical-gfs-analysis", method = "GET") {
  return new Request(
    `https://activity.example/api/map/dynamical/manifest?${search}`,
    { method },
  );
}

async function rejected(search, expectedStatus, expectedCode, env = environment().env) {
  await assert.rejects(
    handleDynamicalRenderManifest(request(search), env),
    (error) => error?.status === expectedStatus && error?.code === expectedCode,
  );
}

const getContext = environment();
const response = await handleDynamicalRenderManifest(
  request("dataset=dynamical-gfs-analysis&bbox=-120,20,-60,50&width=800&height=600"),
  getContext.env,
);
assert.equal(response.status, 200);
assert.deepEqual(Object.keys(await response.json()), [
  "schemaVersion",
  "datasetId",
  "kind",
  "url",
  "coordinates",
  "generatedAt",
  "validTime",
  "variable",
  "units",
  "attribution",
  "status",
]);
assert.equal(getContext.state.assetRequests.length, 1);
assert.equal(
  new URL(getContext.state.assetRequests[0].url).pathname,
  "/data/dynamical/manifest.json",
);
assert.equal(getContext.state.assetRequests[0].method, "GET");

const headResponse = await handleDynamicalRenderManifest(
  request("dataset=dynamical-asos", "HEAD"),
  environment().env,
);
assert.equal(headResponse.status, 200);
assert.equal(await headResponse.text(), "");

const methodResponse = await handleDynamicalRenderManifest(
  request("dataset=dynamical-asos", "POST"),
  environment().env,
);
assert.equal(methodResponse.status, 405);
assert.equal(methodResponse.headers.get("Allow"), "GET, HEAD");

await rejected("dataset=unknown", 400, "invalid_dynamical_dataset");
await rejected(
  "dataset=dynamical-gfs-analysis&bbox=-120,50,-60,20",
  400,
  "invalid_render_viewport",
);
const historicalFallbackResponse = await handleDynamicalRenderManifest(
  request(
    `dataset=dynamical-gfs-analysis&time=${encodeURIComponent("2020-01-01T00:00:00Z")}`,
  ),
  environment().env,
);

assert.equal(
  historicalFallbackResponse.status,
  200,
  "Compatibility mode should return the latest available manifest.",
);

const historicalFallbackManifest = await historicalFallbackResponse.json();

assert.equal(
  historicalFallbackManifest.datasetId,
  "dynamical-gfs-analysis",
);

assert.equal(
  typeof historicalFallbackManifest.validTime,
  "string",
  "The fallback response must preserve the render's actual validTime.",
);

assert.notEqual(
  historicalFallbackManifest.validTime,
  "2020-01-01T00:00:00Z",
  "The fallback must not falsely relabel the current render as historical.",
);

const missingLayer = manifest();
delete missingLayer.layers["dynamical-gfs-analysis"];
await rejected(
  "dataset=dynamical-gfs-analysis",
  404,
  "dynamical_render_unavailable",
  environment(missingLayer).env,
);
await rejected(
  "dataset=dynamical-gfs-analysis",
  503,
  "dynamical_manifest_unavailable",
  environment(manifest(), { contentType: "text/html" }).env,
);

const indexSource = await readFile(path.join(ROOT, "worker", "index.ts"), "utf8");
assert.match(indexSource, /url\.pathname === "\/api\/map\/dynamical\/manifest"/u);
assert.match(indexSource, /handleDynamicalRenderManifest\(request, env\)/u);

console.log(JSON.stringify({
  ok: true,
  validator: "dynamical-render-endpoint",
  datasetIds: datasetIds.length,
  runtimeCases: 8,
}, null, 2));
