import type { EnvironmentName } from "../shared/public-state";
import {
  isActivityScientificDataset,
  isActivityVisualizationSpec,
  isScientificPublicationSummary,
  scientificBundleRecordsAgree,
  type ScientificBundle,
  type ScientificPublicationSummary,
} from "../shared/scientific-visualization";

interface ArtifactFile {
  filename: string;
  contentType: string;
  byteLength: number;
  sha256: string;
  uploadedAt: string;
  url: string;
}

interface ArtifactList {
  environment: EnvironmentName;
  artifactId: string;
  files: ArtifactFile[];
}

const ARTIFACT_LIST_KEYS = ["environment", "artifactId", "files"] as const;
const ARTIFACT_FILE_KEYS = [
  "filename",
  "contentType",
  "byteLength",
  "sha256",
  "uploadedAt",
  "url",
] as const;
const IDENTIFIER_PATTERN = /^[a-z0-9][a-z0-9._-]{0,127}$/;
const FILENAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$/;
const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const UTC_TIMESTAMP_PATTERN =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/;
const ALLOWED_ARTIFACT_TYPES = new Set([
  "application/json",
  "application/octet-stream",
  "image/png",
  "image/svg+xml",
  "text/csv",
  "text/plain",
]);
const MAX_API_JSON_BYTES = 512 * 1024;
const MAX_ARTIFACT_BYTES = 15 * 1024 * 1024;
const MAX_ARTIFACT_FILES = 64;
const BUNDLED_TEST_ROOT = "/science/artifact-phase3-sr03";
const BUNDLED_TEST_PUBLICATION: ScientificPublicationSummary = {
  environment: "test",
  publicationId: "publication-phase3b-viz_2a9e46b71ddb09824835b2f2",
  artifactId: "artifact-phase3-sr03",
  stateHeadHash: "531225e7d753e51510ba9b2bd0898853e71492e41433a708cba758a829636bcb",
  evidenceStateHeadHash:
    "531225e7d753e51510ba9b2bd0898853e71492e41433a708cba758a829636bcb",
  title: "SR-03 line-voltage and timing study",
  publicSummary:
    "The verified intake receipt falls three seconds before the packet's declared transmission time; the retained voltage record also contains a response three seconds before receipt.",
  limitation:
    "This deterministic Phase 3 fixture demonstrates the dashboard and publication path; it is not a production scientific observation.",
  primaryFilename: "scientific-plate.png",
  manifestFilename: "manifest-phase3b.json",
  visualizationFilename: "activity-visualization.json",
  dataFilename: "activity-data.json",
  publishedAt: "2026-07-24T03:17:15Z",
};
const BUNDLED_TEST_FILES = {
  data: {
    filename: "activity-data.json",
    contentType: "application/json",
    byteLength: 268_683,
    sha256: "9674628a1a8b553ecb95cac7906be39789faf8e0686c1b82f9fc4d8a0d352033",
    uploadedAt: "2026-07-24T03:17:15Z",
    url: `${BUNDLED_TEST_ROOT}/activity-data.json`,
  },
  visualization: {
    filename: "activity-visualization.json",
    contentType: "application/json",
    byteLength: 2_352,
    sha256: "bfa1bc139320cca9917e1e6d1d6cff74e540bc898d05d550a7fa27810e0e928c",
    uploadedAt: "2026-07-24T03:17:15Z",
    url: `${BUNDLED_TEST_ROOT}/activity-visualization.json`,
  },
  manifest: {
    filename: "manifest-phase3b.json",
    contentType: "application/json",
    byteLength: 3_257,
    sha256: "e19d46aa18a7f1f20f55391f0e8d8b3b124be0a7ad60c092ba35893c25a06fe8",
    uploadedAt: "2026-07-24T03:17:15Z",
    url: `${BUNDLED_TEST_ROOT}/manifest-phase3b.json`,
  },
  fallback: {
    filename: "scientific-plate.png",
    contentType: "image/png",
    byteLength: 304_990,
    sha256: "b5c6f9ecf11b33dc8c11caaaa9998f4a49f3904f02c724ccbc89399801a8669b",
    uploadedAt: "2026-07-24T03:17:15Z",
    url: `${BUNDLED_TEST_ROOT}/scientific-plate.png`,
  },
} as const satisfies Record<string, ArtifactFile>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(
  record: Record<string, unknown>,
  allowedKeys: readonly string[],
): boolean {
  const allowed = new Set(allowedKeys);
  return Object.keys(record).every((key) => allowed.has(key));
}

function isEnvironment(value: unknown): value is EnvironmentName {
  return value === "live" || value === "test";
}

function isIdentifier(value: unknown): value is string {
  return typeof value === "string" && IDENTIFIER_PATTERN.test(value);
}

function isFilename(value: unknown): value is string {
  return (
    typeof value === "string" &&
    FILENAME_PATTERN.test(value) &&
    !value.includes("..")
  );
}

function isUtcTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    UTC_TIMESTAMP_PATTERN.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}

function normalizeContentType(value: string): string {
  return value.split(";", 1)[0].trim().toLowerCase();
}

function expectedArtifactUrl(
  environment: EnvironmentName,
  artifactId: string,
  filename: string,
): string {
  return `/api/artifacts/${environment}/${encodeURIComponent(artifactId)}/${encodeURIComponent(filename)}`;
}

function decodeJson(bytes: ArrayBuffer, label: string): unknown {
  try {
    const text = new TextDecoder("utf-8", { fatal: true })
      .decode(bytes)
      .replace(/^\uFEFF/, "");
    return JSON.parse(text) as unknown;
  } catch {
    throw new Error(`${label} is not valid UTF-8 JSON.`);
  }
}

async function fetchBytes(url: string, maximumBytes: number): Promise<{
  bytes: ArrayBuffer;
  response: Response;
}> {
  const response = await fetch(url, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${url} returned ${response.status}${detail ? `: ${detail}` : ""}.`);
  }

  const declaredLength = Number.parseInt(
    response.headers.get("Content-Length") ?? "",
    10,
  );
  if (Number.isFinite(declaredLength) && declaredLength > maximumBytes) {
    throw new Error(`${url} exceeds the ${maximumBytes}-byte response limit.`);
  }
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength > maximumBytes) {
    throw new Error(`${url} exceeds the ${maximumBytes}-byte response limit.`);
  }
  return { bytes, response };
}

async function fetchJson(url: string): Promise<unknown> {
  const { bytes } = await fetchBytes(url, MAX_API_JSON_BYTES);
  return decodeJson(bytes, url);
}

async function sha256Hex(bytes: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

async function fetchArtifactJson(file: ArtifactFile): Promise<unknown> {
  const { bytes, response } = await fetchBytes(file.url, MAX_ARTIFACT_BYTES);
  if (bytes.byteLength !== file.byteLength) {
    throw new Error(
      `${file.filename} byte length does not match its artifact registration.`,
    );
  }

  const responseType = normalizeContentType(
    response.headers.get("Content-Type") ?? "",
  );
  if (responseType !== file.contentType) {
    throw new Error(
      `${file.filename} content type does not match its artifact registration.`,
    );
  }
  const responseHash = response.headers.get("X-Content-SHA256");
  if (responseHash !== null && responseHash !== file.sha256) {
    throw new Error(
      `${file.filename} response hash does not match its artifact registration.`,
    );
  }
  if ((await sha256Hex(bytes)) !== file.sha256) {
    throw new Error(
      `${file.filename} content does not match its registered SHA-256 hash.`,
    );
  }
  return decodeJson(bytes, file.filename);
}

function isArtifactFile(
  value: unknown,
  environment: EnvironmentName,
  artifactId: string,
): value is ArtifactFile {
  if (!isRecord(value) || !hasOnlyKeys(value, ARTIFACT_FILE_KEYS)) return false;
  if (
    !isFilename(value.filename) ||
    typeof value.contentType !== "string" ||
    !ALLOWED_ARTIFACT_TYPES.has(value.contentType) ||
    typeof value.byteLength !== "number" ||
    !Number.isSafeInteger(value.byteLength) ||
    value.byteLength <= 0 ||
    value.byteLength > MAX_ARTIFACT_BYTES ||
    typeof value.sha256 !== "string" ||
    !SHA256_PATTERN.test(value.sha256) ||
    !isUtcTimestamp(value.uploadedAt) ||
    typeof value.url !== "string"
  ) {
    return false;
  }
  return value.url === expectedArtifactUrl(environment, artifactId, value.filename);
}

function isArtifactList(value: unknown): value is ArtifactList {
  if (!isRecord(value) || !hasOnlyKeys(value, ARTIFACT_LIST_KEYS)) return false;
  if (
    !isEnvironment(value.environment) ||
    !isIdentifier(value.artifactId) ||
    !Array.isArray(value.files) ||
    value.files.length === 0 ||
    value.files.length > MAX_ARTIFACT_FILES ||
    !value.files.every((file) =>
      isArtifactFile(file, value.environment as EnvironmentName, value.artifactId as string),
    )
  ) {
    return false;
  }
  const filenames = value.files.map((file) => file.filename);
  return new Set(filenames).size === filenames.length;
}

function requireArtifact(
  byName: ReadonlyMap<string, ArtifactFile>,
  filename: string,
): ArtifactFile {
  const file = byName.get(filename);
  if (!file) {
    throw new Error(`Publication does not include ${filename}.`);
  }
  return file;
}

function requireJsonArtifact(file: ArtifactFile): void {
  if (file.contentType !== "application/json") {
    throw new Error(`${file.filename} must be registered as application/json.`);
  }
}

export async function loadLatestScientificBundle(
  environment: EnvironmentName,
): Promise<ScientificBundle | null> {
  try {
    const publicationValue = await fetchJson(
      `/api/publications/latest?environment=${encodeURIComponent(environment)}`,
    );
    if (publicationValue !== null) {
      if (!isScientificPublicationSummary(publicationValue)) {
        throw new Error("Latest-publication response failed the Phase 3B schema check.");
      }
      if (publicationValue.environment !== environment) {
        throw new Error("Latest-publication environment does not match the request.");
      }
      if (
        publicationValue.visualizationFilename !== null &&
        publicationValue.dataFilename !== null
      ) {
        return await loadScientificBundle(publicationValue);
      }
    }
  } catch (error) {
    if (environment !== "test") throw error;
  }

  return environment === "test" ? loadBundledTestScientificBundle() : null;
}

export async function loadBundledTestScientificBundle(): Promise<ScientificBundle> {
  if (!isScientificPublicationSummary(BUNDLED_TEST_PUBLICATION)) {
    throw new Error("Bundled test publication failed its internal schema check.");
  }
  const specValue = await fetchArtifactJson(BUNDLED_TEST_FILES.visualization);
  if (!isActivityVisualizationSpec(specValue)) {
    throw new Error("Bundled Activity visualization specification failed validation.");
  }
  const datasetValue = await fetchArtifactJson(BUNDLED_TEST_FILES.data);
  if (!isActivityScientificDataset(datasetValue)) {
    throw new Error("Bundled Activity scientific dataset failed validation.");
  }
  if (
    !scientificBundleRecordsAgree(
      BUNDLED_TEST_PUBLICATION,
      specValue,
      datasetValue,
    )
  ) {
    throw new Error("Bundled publication, specification, and dataset do not agree.");
  }
  return {
    delivery: "bundled-test",
    publication: BUNDLED_TEST_PUBLICATION,
    spec: specValue,
    dataset: datasetValue,
    fallbackUrl: BUNDLED_TEST_FILES.fallback.url,
    manifestUrl: BUNDLED_TEST_FILES.manifest.url,
  };
}

async function loadScientificBundle(
  publication: ScientificPublicationSummary,
): Promise<ScientificBundle> {
  const listValue = await fetchJson(
    `/api/artifacts/${publication.environment}/${encodeURIComponent(publication.artifactId)}`,
  );
  if (!isArtifactList(listValue)) {
    throw new Error("Artifact listing failed the Phase 3B schema check.");
  }
  if (
    listValue.environment !== publication.environment ||
    listValue.artifactId !== publication.artifactId
  ) {
    throw new Error("Publication and artifact listing identifiers do not agree.");
  }

  const byName = new Map(listValue.files.map((file) => [file.filename, file]));
  if (
    publication.visualizationFilename === null ||
    publication.dataFilename === null
  ) {
    throw new Error("Publication does not declare an interactive scientific bundle.");
  }

  const visualizationFile = requireArtifact(
    byName,
    publication.visualizationFilename,
  );
  requireJsonArtifact(visualizationFile);
  const specValue = await fetchArtifactJson(visualizationFile);
  if (!isActivityVisualizationSpec(specValue)) {
    throw new Error("Activity visualization specification failed validation.");
  }

  if (publication.dataFilename !== specValue.datasetFilename) {
    throw new Error("Publication and specification dataset filenames do not agree.");
  }
  if (publication.primaryFilename !== specValue.fallbackFilename) {
    throw new Error("Publication and specification fallback filenames do not agree.");
  }
  if (publication.manifestFilename !== specValue.manifestFilename) {
    throw new Error("Publication and specification manifest filenames do not agree.");
  }

  const dataFile = requireArtifact(byName, publication.dataFilename);
  const fallbackFile = requireArtifact(byName, specValue.fallbackFilename);
  const manifestFile = requireArtifact(byName, specValue.manifestFilename);
  requireJsonArtifact(dataFile);
  requireJsonArtifact(manifestFile);

  const datasetValue = await fetchArtifactJson(dataFile);
  if (!isActivityScientificDataset(datasetValue)) {
    throw new Error("Activity scientific dataset failed validation.");
  }
  if (!scientificBundleRecordsAgree(publication, specValue, datasetValue)) {
    throw new Error(
      "Publication, specification, and dataset scientific identities do not agree.",
    );
  }

  return {
    delivery: "published",
    publication,
    spec: specValue,
    dataset: datasetValue,
    fallbackUrl: fallbackFile.url,
    manifestUrl: manifestFile.url,
  };
}
