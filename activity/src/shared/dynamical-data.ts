import type { PublicReportRecord } from "./external-map-layers";

export type DynamicalDatasetId =
  | "dynamical-asos"
  | "dynamical-gfs-analysis"
  | "dynamical-hrrr-analysis"
  | "dynamical-mrms-analysis"
  | "dynamical-imerg-late";

export type DynamicalEvidenceRole =
  | "surface-observation"
  | "model-analysis"
  | "radar-multisensor-analysis"
  | "satellite-precipitation-estimate";

export interface DynamicalDatasetDefinition {
  id: DynamicalDatasetId;
  /** Stable key shared with the signed Python analysis worker. */
  analysisKey: "asos" | "gfs" | "hrrr" | "mrms" | "imerg_late";
  catalogId: string;
  label: string;
  shortLabel: string;
  role: DynamicalEvidenceRole;
  sourceUrl: string;
  license: "CC BY 4.0" | "Not stated on experimental catalog page";
  experimental: boolean;
  spatialDomain: string;
  spatialResolution: string;
  temporalStart: string;
  temporalResolution: string;
  coverageBbox: readonly [number, number, number, number];
  variables: readonly string[];
  limitation: string;
}

/**
 * Registry reviewed against the public Dynamical catalog. These are evidence
 * sources, not rendered weather tiles: the map displays their declared
 * coverage and query-compatible report windows while report-scoped workers
 * derive immutable meteorological point/window results.
 */
export const DYNAMICAL_DATASETS: readonly DynamicalDatasetDefinition[] = [
  {
    id: "dynamical-asos",
    analysisKey: "asos",
    catalogId: "asos-parquet",
    label: "Airport surface observations",
    shortLabel: "ASOS/AWOS",
    role: "surface-observation",
    sourceUrl: "https://dynamical.org/catalog/asos-parquet/",
    license: "Not stated on experimental catalog page",
    experimental: true,
    spatialDomain: "Global station network",
    spatialResolution: "Station observations",
    temporalStart: "1940-01-01T00:00:00Z",
    temporalResolution: "Hourly METAR",
    coverageBbox: [-179.5, -85, 179.5, 85],
    variables: [
      "temperature",
      "dew point",
      "precipitation",
      "wind",
      "visibility",
      "pressure",
    ],
    limitation:
      "Experimental, station-dependent observations received without resampling, interpolation, or added quality control.",
  },
  {
    id: "dynamical-gfs-analysis",
    analysisKey: "gfs",
    catalogId: "noaa-gfs-analysis",
    label: "Global weather analysis",
    shortLabel: "NOAA GFS",
    role: "model-analysis",
    sourceUrl: "https://dynamical.org/catalog/noaa-gfs-analysis/",
    license: "CC BY 4.0",
    experimental: false,
    spatialDomain: "Global",
    spatialResolution: "0.25 degrees (~20 km)",
    temporalStart: "2021-05-01T00:00:00Z",
    temporalResolution: "Hourly",
    coverageBbox: [-179.5, -89.5, 179.5, 89.5],
    variables: [
      "cloud ceiling",
      "total cloud cover",
      "precipitation",
      "humidity",
      "temperature",
      "surface pressure",
      "10 m wind",
    ],
    limitation:
      "A model analysis is a gridded reconstruction, not an observation at the witness location.",
  },
  {
    id: "dynamical-hrrr-analysis",
    analysisKey: "hrrr",
    catalogId: "noaa-hrrr-analysis",
    label: "High-resolution CONUS analysis",
    shortLabel: "NOAA HRRR",
    role: "model-analysis",
    sourceUrl: "https://dynamical.org/catalog/noaa-hrrr-analysis/",
    license: "CC BY 4.0",
    experimental: false,
    spatialDomain: "Continental United States",
    spatialResolution: "3 km",
    temporalStart: "2014-10-01T00:00:00Z",
    temporalResolution: "Hourly",
    coverageBbox: [-134, 20, -60, 54],
    variables: [
      "composite reflectivity",
      "cloud ceiling",
      "total cloud cover",
      "precipitation",
      "humidity",
      "temperature",
      "wind gust",
      "10 m wind",
    ],
    limitation:
      "A model analysis with material missing source files before August 2018 and some variable gaps in early versions.",
  },
  {
    id: "dynamical-mrms-analysis",
    analysisKey: "mrms",
    catalogId: "noaa-mrms-conus-analysis-hourly",
    label: "CONUS radar and precipitation analysis",
    shortLabel: "NOAA MRMS",
    role: "radar-multisensor-analysis",
    sourceUrl:
      "https://dynamical.org/catalog/noaa-mrms-conus-analysis-hourly/",
    license: "CC BY 4.0",
    experimental: false,
    spatialDomain: "Continental United States",
    spatialResolution: "0.01 degrees (~1 km)",
    temporalStart: "2014-11-01T00:00:00Z",
    temporalResolution: "Hourly",
    coverageBbox: [-129.995, 20.005, -60.005, 54.995],
    variables: [
      "precipitation type",
      "precipitation rate",
      "radar and multisensor precipitation",
    ],
    limitation:
      "Radar coverage varies within the published envelope, and some early hours contain unavailable values.",
  },
  {
    id: "dynamical-imerg-late",
    analysisKey: "imerg_late",
    catalogId: "nasa-imerg-analysis-late",
    label: "Global satellite precipitation",
    shortLabel: "NASA IMERG Late",
    role: "satellite-precipitation-estimate",
    sourceUrl: "https://dynamical.org/catalog/nasa-imerg-analysis-late/",
    license: "CC BY 4.0",
    experimental: false,
    spatialDomain: "Global",
    spatialResolution: "0.1 degrees (~10 km)",
    temporalStart: "1998-01-01T00:00:00Z",
    temporalResolution: "30 minutes",
    coverageBbox: [-179.95, -89.95, 179.95, 89.95],
    variables: ["precipitation rate", "precipitation quality index"],
    limitation:
      "A merged satellite estimate; pre-GPM-era values and high-latitude estimates generally have greater uncertainty.",
  },
] as const;

export type DynamicalPlanStatus =
  | "eligible"
  | "station-check-required"
  | "outside-spatial-coverage"
  | "outside-temporal-coverage";

export interface DynamicalDatasetPlanEntry {
  datasetId: DynamicalDatasetId;
  catalogId: string;
  status: DynamicalPlanStatus;
  reason: string;
  queryStart: string;
  queryEnd: string;
  spatialEnvelope: readonly [number, number, number, number];
  variables: readonly string[];
  limitation: string;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function uncertainUtcWindow(observedAt: string): { start: string; end: string } {
  const parsed = new Date(observedAt);
  if (Number.isNaN(parsed.valueOf())) {
    throw new Error("Report observation date is invalid.");
  }
  const day = parsed.toISOString().slice(0, 10);
  const start = new Date(`${day}T00:00:00.000Z`);
  start.setUTCDate(start.getUTCDate() - 1);
  const end = new Date(start);
  end.setUTCDate(end.getUTCDate() + 3);
  return { start: start.toISOString(), end: end.toISOString() };
}

function reportEnvelope(
  latitude: number,
  longitude: number,
  radiusKm = 50,
): readonly [number, number, number, number] {
  const latitudeDelta = radiusKm / 111;
  const longitudeDelta = radiusKm /
    Math.max(25, 111 * Math.cos((latitude * Math.PI) / 180));
  return [
    clamp(longitude - longitudeDelta, -180, 180),
    clamp(latitude - latitudeDelta, -90, 90),
    clamp(longitude + longitudeDelta, -180, 180),
    clamp(latitude + latitudeDelta, -90, 90),
  ];
}

function bboxIntersects(
  left: readonly [number, number, number, number],
  right: readonly [number, number, number, number],
): boolean {
  return !(
    left[2] < right[0] ||
    left[0] > right[2] ||
    left[3] < right[1] ||
    left[1] > right[3]
  );
}

export function planDynamicalEvidence(
  report: Pick<PublicReportRecord, "observedAt" | "latitude" | "longitude">,
): DynamicalDatasetPlanEntry[] {
  const window = uncertainUtcWindow(report.observedAt);
  const envelope = reportEnvelope(report.latitude, report.longitude);

  return DYNAMICAL_DATASETS.map((dataset) => {
    let status: DynamicalPlanStatus = "eligible";
    let reason =
      "The date-only report window (with a one-day UTC buffer on each side) intersects the dataset's declared temporal and spatial coverage.";
    if (window.end <= dataset.temporalStart) {
      status = "outside-temporal-coverage";
      reason = `The dataset begins ${dataset.temporalStart.slice(0, 10)}, after the report date.`;
    } else if (!bboxIntersects(envelope, dataset.coverageBbox)) {
      status = "outside-spatial-coverage";
      reason = "The privacy-quantized report envelope does not intersect the declared dataset domain.";
    } else if (dataset.id === "dynamical-asos") {
      status = "station-check-required";
      reason =
        "The date is covered, but a worker must identify nearby reporting stations and retain distance and station metadata.";
    }
    return {
      datasetId: dataset.id,
      catalogId: dataset.catalogId,
      status,
      reason,
      queryStart: window.start,
      queryEnd: window.end,
      spatialEnvelope: envelope,
      variables: dataset.variables,
      limitation: dataset.limitation,
    };
  });
}

export function dynamicalCoverageCollection() {
  return {
    type: "FeatureCollection" as const,
    features: DYNAMICAL_DATASETS.map((dataset) => {
      const [west, south, east, north] = dataset.coverageBbox;
      // Web Mercator cannot represent the poles; preserve the scientific bbox
      // in the registry while clipping only its display geometry.
      const displaySouth = Math.max(-85, south);
      const displayNorth = Math.min(85, north);
      return {
        type: "Feature" as const,
        id: dataset.id,
        geometry: {
          type: "Polygon" as const,
          coordinates: [[
            [west, displaySouth],
            [east, displaySouth],
            [east, displayNorth],
            [west, displayNorth],
            [west, displaySouth],
          ]],
        },
        properties: {
          id: dataset.id,
          catalogId: dataset.catalogId,
          label: dataset.label,
          shortLabel: dataset.shortLabel,
          role: dataset.role,
          domain: dataset.spatialDomain,
          spatialResolution: dataset.spatialResolution,
          temporalStart: dataset.temporalStart,
          temporalResolution: dataset.temporalResolution,
          experimental: dataset.experimental,
          sourceUrl: dataset.sourceUrl,
          limitation: dataset.limitation,
        },
      };
    }),
  };
}

export interface DynamicalReportContextProperties {
  reportId: string;
  title: string;
  locationName: string;
  observedAt: string;
  datasetIds: string;
  datasetCount: number;
}

/**
 * Projects public reports that overlap at least one Dynamical dataset in time
 * and space. These points describe where a bounded query can be attempted;
 * they are deliberately not represented as weather observations.
 */
export function dynamicalReportContextCollection(
  reports: readonly PublicReportRecord[],
) {
  return {
    type: "FeatureCollection" as const,
    features: reports.slice(0, 2_000).flatMap((report) => {
      const datasetIds = planDynamicalEvidence(report)
        .filter(
          ({ status }) =>
            status === "eligible" || status === "station-check-required",
        )
        .map(({ datasetId }) => datasetId);
      if (datasetIds.length === 0) return [];
      return [{
        type: "Feature" as const,
        id: `dynamical-context:${report.reportId}`,
        geometry: {
          type: "Point" as const,
          coordinates: [report.longitude, report.latitude] as [number, number],
        },
        properties: {
          reportId: report.reportId,
          title: report.title,
          locationName: report.locationName,
          observedAt: report.observedAt,
          datasetIds: datasetIds.join(","),
          datasetCount: datasetIds.length,
        } satisfies DynamicalReportContextProperties,
      }];
    }),
  };
}

export function isDynamicalDatasetId(value: string): value is DynamicalDatasetId {
  return DYNAMICAL_DATASETS.some((dataset) => dataset.id === value);
}
