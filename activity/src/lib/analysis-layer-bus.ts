import type { PublicAnomalyMapLayer } from "../shared/geospatial";
import {
  analyzeFacilityScience,
  initialScienceControls,
} from "../shared/facility-science";
import {
  ENVIRONMENTAL_FACILITIES,
  isEnvironmentalFacilityId,
  type EnvironmentalFacilityId,
} from "../shared/environmental-context";

const STORAGE_KEY = "missing-interior:analysis-map-layers:v1";
const EVENT_NAME = "missing-interior:analysis-map-layers";

interface StoredFacilityLayers {
  facilityId: EnvironmentalFacilityId;
  updatedAt: string;
  layers: PublicAnomalyMapLayer[];
}

type StoredLayerRecord = Partial<
  Record<EnvironmentalFacilityId, StoredFacilityLayers>
>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isLayer(value: unknown): value is PublicAnomalyMapLayer {
  if (!isRecord(value) || typeof value.layerId !== "string") return false;
  if (value.kind === "trajectory") return Array.isArray(value.samples);
  if (value.kind === "heatmap") return Array.isArray(value.cells);
  return false;
}

function readRecord(): StoredLayerRecord {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed)) return {};
    const result: StoredLayerRecord = {};
    for (const [facilityId, candidate] of Object.entries(parsed)) {
      if (
        !isEnvironmentalFacilityId(facilityId) ||
        !isRecord(candidate) ||
        typeof candidate.updatedAt !== "string" ||
        !Array.isArray(candidate.layers)
      ) {
        continue;
      }
      const layers = candidate.layers.filter(isLayer);
      result[facilityId] = { facilityId, updatedAt: candidate.updatedAt, layers };
    }
    return result;
  } catch {
    return {};
  }
}

function flatten(record: StoredLayerRecord): PublicAnomalyMapLayer[] {
  return (Object.keys(ENVIRONMENTAL_FACILITIES) as EnvironmentalFacilityId[])
    .flatMap((facilityId) => {
      const stored = record[facilityId];
      if (stored) return stored.layers;
      return analyzeFacilityScience(
        facilityId,
        initialScienceControls(facilityId),
        false,
        0,
      ).mapLayers;
    });
}

export function currentAnalysisMapLayers(): PublicAnomalyMapLayer[] {
  return typeof window === "undefined" ? [] : flatten(readRecord());
}

export function publishAnalysisMapLayers(
  facilityId: EnvironmentalFacilityId,
  layers: readonly PublicAnomalyMapLayer[],
): void {
  const record = readRecord();
  record[facilityId] = {
    facilityId,
    updatedAt: new Date().toISOString(),
    layers: layers.map((layer) => structuredClone(layer)),
  };
  window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(record));
  window.dispatchEvent(
    new CustomEvent<PublicAnomalyMapLayer[]>(EVENT_NAME, {
      detail: flatten(record),
    }),
  );
}

export function subscribeAnalysisMapLayers(
  listener: (layers: PublicAnomalyMapLayer[]) => void,
): () => void {
  const onLayers = (event: Event) => {
    const detail = (event as CustomEvent<PublicAnomalyMapLayer[]>).detail;
    listener(Array.isArray(detail) ? detail.filter(isLayer) : currentAnalysisMapLayers());
  };
  window.addEventListener(EVENT_NAME, onLayers);
  return () => window.removeEventListener(EVENT_NAME, onLayers);
}
