export const ENVIRONMENTAL_FACILITIES = {
  boundary_array: {
    name: "Boundary Array",
    label: "Black Rock Sector, Nevada",
    latitude: 40.88,
    longitude: -119.05,
  },
  aeronautical_incident_center: {
    name: "Aeronautical Incident Center",
    label: "Allegheny Sector, West Virginia",
    latitude: 38.73,
    longitude: -80.21,
  },
  aerial_phenomena_archive: {
    name: "Aerial Phenomena Archive",
    label: "Driftless Sector, Wisconsin",
    latitude: 43.25,
    longitude: -90.88,
  },
  holography_laboratory: {
    name: "Holography Laboratory",
    label: "San Luis Sector, Colorado",
    latitude: 37.73,
    longitude: -105.91,
  },
  subsurface_resonance_station: {
    name: "Subsurface Resonance Station",
    label: "Cascadia Sector, Washington",
    latitude: 47.45,
    longitude: -123.53,
  },
  quantum_state_institute: {
    name: "Quantum State Institute",
    label: "Adirondack Sector, New York",
    latitude: 44.12,
    longitude: -74.31,
  },
} as const;

export type EnvironmentalFacilityId = keyof typeof ENVIRONMENTAL_FACILITIES;
export type EnvironmentalSourceId = "nws" | "usgs" | "swpc";

export interface EnvironmentalSourceStatus {
  id: EnvironmentalSourceId;
  label: string;
  status: "current" | "unavailable";
  observedAt: string | null;
  detail: string;
  sourceUrl: string;
}

export interface EnvironmentalReading {
  id:
    | "temperature"
    | "wind"
    | "visibility"
    | "pressure"
    | "earthquakes"
    | "strongest-earthquake"
    | "solar-wind"
    | "planetary-k";
  label: string;
  value: number | null;
  unit: string;
  source: EnvironmentalSourceId;
}

export interface EnvironmentalIndicator {
  id: "atmospheric-obscuration" | "seismic-background" | "radio-propagation";
  label: string;
  value: number;
  detail: string;
}

export interface EnvironmentalContextSnapshot {
  schemaVersion: "1.0.0";
  environment: "test";
  facilityId: EnvironmentalFacilityId;
  facilityName: string;
  facilityLabel: string;
  latitude: number;
  longitude: number;
  retrievedAt: string;
  readings: EnvironmentalReading[];
  indicators: EnvironmentalIndicator[];
  sources: EnvironmentalSourceStatus[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isEnvironmentalFacilityId(
  value: unknown,
): value is EnvironmentalFacilityId {
  return typeof value === "string" && value in ENVIRONMENTAL_FACILITIES;
}

export function normalizeEnvironmentalContext(
  value: unknown,
): EnvironmentalContextSnapshot | null {
  if (
    !isRecord(value) ||
    value.schemaVersion !== "1.0.0" ||
    value.environment !== "test" ||
    !isEnvironmentalFacilityId(value.facilityId) ||
    typeof value.facilityName !== "string" ||
    typeof value.facilityLabel !== "string" ||
    typeof value.latitude !== "number" ||
    !Number.isFinite(value.latitude) ||
    typeof value.longitude !== "number" ||
    !Number.isFinite(value.longitude) ||
    typeof value.retrievedAt !== "string" ||
    !Array.isArray(value.readings) ||
    !Array.isArray(value.indicators) ||
    !Array.isArray(value.sources)
  ) {
    return null;
  }

  return value as unknown as EnvironmentalContextSnapshot;
}
