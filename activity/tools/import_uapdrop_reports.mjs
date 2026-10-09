import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const SOURCE_URL = "https://www.uapdrop.com/rest/v1/public/sightings.json";
const SOURCE_PAGE = "https://www.uapdrop.com/data.html";
const MAX_SOURCE_BYTES = 50_000_000;
const MAX_PUBLISHED_REPORTS = 6_000;
const CONUS_BOUNDS = {
  west: -138,
  south: 20,
  east: -58,
  north: 56,
};

function boundedText(value, maximum) {
  return typeof value === "string" ? value.trim().slice(0, maximum) : "";
}

function safeSourceUrl(value) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return (
      url.protocol === "https:" &&
      (url.hostname === "catalog.archives.gov" ||
        url.hostname === "www.archives.gov")
    ) ? url.toString() : null;
  } catch {
    return null;
  }
}

function normalizeReport(value) {
  if (!value || typeof value !== "object") return null;
  const latitude = Number(value.latitude);
  const longitude = Number(value.longitude);
  const observed = new Date(value.observedAt);
  if (
    !Number.isFinite(latitude) ||
    !Number.isFinite(longitude) ||
    latitude < CONUS_BOUNDS.south ||
    latitude > CONUS_BOUNDS.north ||
    longitude < CONUS_BOUNDS.west ||
    longitude > CONUS_BOUNDS.east ||
    Number.isNaN(observed.valueOf())
  ) {
    return null;
  }
  const sourceKey = boundedText(value.sourceKey, 64) || "archive";
  const externalId = boundedText(value.externalId, 128);
  if (!externalId) return null;
  return {
    reportId: `${sourceKey}:${externalId}`,
    observedAt: observed.toISOString(),
    latitude,
    longitude,
    title: boundedText(value.title, 180) || "Public report",
    locationName: boundedText(value.locationName, 180),
    coordinatePrecision: boundedText(value.coordinatePrecision, 64) || null,
    sourceKey,
    sourceUrl: safeSourceUrl(value.sourceUrl),
  };
}

function sampleEvenly(records, maximum) {
  if (records.length <= maximum) return records;
  return Array.from({ length: maximum }, (_, index) => {
    const sourceIndex = Math.round((index * (records.length - 1)) / (maximum - 1));
    return records[sourceIndex];
  });
}

async function loadSource(inputPath) {
  if (inputPath) {
    const body = await readFile(path.resolve(inputPath), "utf8");
    if (Buffer.byteLength(body) > MAX_SOURCE_BYTES) {
      throw new Error("Source archive exceeds the 50 MB ingest limit.");
    }
    return JSON.parse(body);
  }
  const response = await fetch(SOURCE_URL, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`UAPDrop returned ${response.status}.`);
  }
  const body = await response.text();
  if (Buffer.byteLength(body) > MAX_SOURCE_BYTES) {
    throw new Error("Source archive exceeds the 50 MB ingest limit.");
  }
  return JSON.parse(body);
}

const inputPath = process.argv[2];
const outputPath = path.resolve(
  process.cwd(),
  "public",
  "science",
  "uap-public-reports.json",
);
const source = await loadSource(inputPath);
if (!Array.isArray(source)) {
  throw new Error("UAPDrop source must be a JSON array.");
}

const eligible = source
  .map(normalizeReport)
  .filter(Boolean)
  .sort((left, right) =>
    left.observedAt.localeCompare(right.observedAt) ||
    left.reportId.localeCompare(right.reportId));
const reports = sampleEvenly(eligible, MAX_PUBLISHED_REPORTS);
const output = {
  schemaVersion: "1.0.0",
  source: {
    name: "UAPDrop Sightings Open Dataset",
    pageUrl: SOURCE_PAGE,
    dataUrl: SOURCE_URL,
    license: "CC BY 4.0",
    licenseUrl: "https://creativecommons.org/licenses/by/4.0/",
  },
  selection: {
    bounds: CONUS_BOUNDS,
    eligibleCount: eligible.length,
    publishedCount: reports.length,
    method:
      "Deterministic even sampling over chronologically sorted geocoded reports.",
  },
  timeExtent: {
    start: reports.at(0)?.observedAt ?? null,
    end: reports.at(-1)?.observedAt ?? null,
  },
  reports,
};

await mkdir(path.dirname(outputPath), { recursive: true });
await writeFile(outputPath, `${JSON.stringify(output)}\n`, "utf8");
console.log(JSON.stringify({
  ok: true,
  outputPath,
  sourceCount: source.length,
  eligibleCount: eligible.length,
  publishedCount: reports.length,
  start: output.timeExtent.start,
  end: output.timeExtent.end,
}, null, 2));
