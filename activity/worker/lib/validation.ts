import {
  isPublicActivitySnapshot,
  type EnvironmentName,
  type PublicActivitySnapshot,
} from "../../src/shared/public-state";
import { HttpError } from "./errors";

const IDENTIFIER_PATTERN = /^[a-z0-9][a-z0-9._-]{0,127}$/;
const FILENAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$/;
const SHA256_PATTERN = /^[a-f0-9]{64}$/;

export function parseEnvironment(value: string | null): EnvironmentName {
  if (value === "live" || value === "test") {
    return value;
  }
  throw new HttpError(400, "invalid_environment", "Environment must be live or test.");
}

export function parseIdentifier(value: string, label: string): string {
  if (!IDENTIFIER_PATTERN.test(value)) {
    throw new HttpError(400, "invalid_identifier", `${label} has an invalid format.`);
  }
  return value;
}

export function parseFilename(value: string): string {
  if (!FILENAME_PATTERN.test(value) || value.includes("..")) {
    throw new HttpError(400, "invalid_filename", "Artifact filename has an invalid format.");
  }
  return value;
}

export function parseSha256(value: unknown, label: string): string {
  if (typeof value !== "string" || !SHA256_PATTERN.test(value)) {
    throw new HttpError(400, "invalid_sha256", `${label} must be lowercase SHA-256 hex.`);
  }
  return value;
}

export function parseSnapshot(value: unknown): PublicActivitySnapshot {
  if (!isPublicActivitySnapshot(value)) {
    throw new HttpError(400, "invalid_snapshot", "The public-state payload does not match a supported public-state schema (2.0–2.4).");
  }
  if (value.source !== "hypha") {
    throw new HttpError(400, "invalid_snapshot_source", "Published snapshots must use source=hypha.");
  }
  if (value.revision < 1) {
    throw new HttpError(400, "invalid_revision", "Published snapshot revision must be at least one.");
  }
  if (!value.stateHeadHash.trim()) {
    throw new HttpError(400, "invalid_state_head", "stateHeadHash cannot be empty.");
  }
  return value;
}

export interface PublicationPayload {
  environment: EnvironmentName;
  publicationId: string;
  artifactId: string;
  stateHeadHash: string;
  evidenceStateHeadHash: string | null;
  title: string;
  publicSummary: string;
  limitation: string;
  primaryFilename: string;
  manifestFilename: string | null;
  visualizationFilename: string | null;
  dataFilename: string | null;
  publishedAt: string;
}

function optionalFilename(record: Record<string, unknown>, key: string): string | null {
  const value = record[key];
  if (value === null || value === undefined) return null;
  return parseFilename(String(value));
}

export function parsePublication(value: unknown): PublicationPayload {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new HttpError(400, "invalid_publication", "Publication payload must be an object.");
  }

  const record = value as Record<string, unknown>;
  const environment = parseEnvironment(
    typeof record.environment === "string" ? record.environment : null,
  );
  const publicationId = parseIdentifier(String(record.publicationId ?? ""), "publicationId");
  const artifactId = parseIdentifier(String(record.artifactId ?? ""), "artifactId");
  const primaryFilename = parseFilename(String(record.primaryFilename ?? ""));
  const manifestFilename = optionalFilename(record, "manifestFilename");
  const visualizationFilename = optionalFilename(record, "visualizationFilename");
  const dataFilename = optionalFilename(record, "dataFilename");

  for (const key of [
    "stateHeadHash",
    "title",
    "publicSummary",
    "limitation",
    "publishedAt",
  ] as const) {
    if (typeof record[key] !== "string" || !record[key].trim()) {
      throw new HttpError(400, "invalid_publication", `${key} must be a non-empty string.`);
    }
  }

  const evidenceStateHeadHash =
    record.evidenceStateHeadHash === null || record.evidenceStateHeadHash === undefined
      ? null
      : String(record.evidenceStateHeadHash);
  if (evidenceStateHeadHash !== null && !evidenceStateHeadHash.trim()) {
    throw new HttpError(
      400,
      "invalid_publication",
      "evidenceStateHeadHash must be null or a non-empty string.",
    );
  }

  if ((visualizationFilename === null) !== (dataFilename === null)) {
    throw new HttpError(
      400,
      "invalid_publication",
      "visualizationFilename and dataFilename must be supplied together.",
    );
  }

  return {
    environment,
    publicationId,
    artifactId,
    stateHeadHash: record.stateHeadHash as string,
    evidenceStateHeadHash,
    title: record.title as string,
    publicSummary: record.publicSummary as string,
    limitation: record.limitation as string,
    primaryFilename,
    manifestFilename,
    visualizationFilename,
    dataFilename,
    publishedAt: record.publishedAt as string,
  };
}
