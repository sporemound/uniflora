import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import maplibregl, {
  type GeoJSONSource,
  type Map as MapLibreMap,
  type MapMouseEvent,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  EXTERNAL_MAP_LAYERS,
  type ExternalMapLayerId,
  latestCompleteUtcDate,
  nasaTrueColorTileUrl,
  NOAA_RADAR_TILE_URL,
  nwsAlertUrls,
  type PublicReportRecord,
  sanitizeNwsAlertCollection,
  sanitizePublicReportSnapshot,
} from "../shared/external-map-layers";
import {
  DYNAMICAL_DATASETS,
  dynamicalCoverageCollection,
  dynamicalReportContextCollection,
  isDynamicalDatasetId,
  type DynamicalDatasetId,
} from "../shared/dynamical-data";
import {
  dynamicalRenderManifestUrl,
  parseDynamicalRenderManifest,
  type DynamicalRenderManifest,
} from "../shared/dynamical-map-render";
import type { UfosintActor } from "../shared/ufosint-sidequest";
import { UfosintSidequestPanel } from "./UfosintSidequestPanel";
import type { PublicAnomalyMapLayer } from "../shared/geospatial";
import { facilityMapCoordinate } from "../shared/facility-geography";
import type { PublicLocation } from "../shared/public-state";

interface GeographicFieldMapProps {
  locations: readonly PublicLocation[];
  anomalyLayers: readonly PublicAnomalyMapLayer[];
  selectedId: string;
  onSelect: (locationId: string) => void;
  sessionToken?: string | null;
  initialSidequestReportId?: string | null;
  onSidequestReportIdChange: (reportId: string | null) => void;
  participant?: UfosintActor | null;
  readOnly?: boolean;
}

const FACILITY_SOURCE = "uniflora-facilities";
const TRAJECTORY_SOURCE = "uniflora-trajectories";
const HEAT_SOURCE = "uniflora-heat";
const SATELLITE_SOURCE = "nasa-true-color";
const RADAR_SOURCE = "noaa-radar";
const ALERT_SOURCE = "nws-alerts";
const REPORT_SOURCE = "uap-public-reports";
const DYNAMICAL_SOURCE = "dynamical-dataset-coverage";
const DYNAMICAL_CONTEXT_SOURCE = "dynamical-report-context";
const DYNAMICAL_RENDER_SOURCE_PREFIX = "dynamical-render-source:";
const DYNAMICAL_RENDER_LAYER_PREFIX = "dynamical-render-layer:";
const SATELLITE_LAYER = "nasa-true-color";
const RADAR_LAYER = "noaa-radar";
const ALERT_FILL_LAYER = "nws-alerts-fill";
const ALERT_LINE_LAYER = "nws-alerts-line";
const REPORT_POINT_LAYER = "uap-public-reports";
const REPORT_HIT_LAYER = "uap-public-reports-hit-targets";
const DYNAMICAL_CONTEXT_LAYER = "dynamical-report-context-points";
const EMPTY_COLLECTION = { type: "FeatureCollection" as const, features: [] };
const ANALYSIS_VISIBILITY_STORAGE_KEY =
  "missing-interior:map-analysis-visibility:v1";

interface AnalysisLayerVisibility {
  enabled: boolean;
  hiddenLayerIds: string[];
}

type DynamicalRenderPhase = "idle" | "loading" | "ready" | "error";

interface DynamicalRenderState {
  phase: DynamicalRenderPhase;
  detail: string;
  kind: DynamicalRenderManifest["kind"] | null;
  variable: string | null;
  units: string | null;
  validTime: string | null;
  generatedAt: string | null;
  attribution: string | null;
}

type ExternalLayerSettings = Record<
  ExternalMapLayerId,
  { visible: boolean; opacity: number }
>;

const DEFAULT_EXTERNAL_SETTINGS = {
  "nasa-true-color": { visible: false, opacity: 0.82 },
  "noaa-radar": { visible: false, opacity: 0.72 },
  "nws-alerts": { visible: false, opacity: 0.46 },
  "uap-public-reports": { visible: false, opacity: 0.76 },
  ...Object.fromEntries(
    DYNAMICAL_DATASETS.map((dataset) => [
      dataset.id,
      {
        visible: dataset.id === "dynamical-gfs-analysis",
        opacity: 0.76,
      },
    ]),
  ),
} as ExternalLayerSettings;

const DYNAMICAL_COLORS: Record<DynamicalDatasetId, string> = {
  "dynamical-asos": "#9ccfbd",
  "dynamical-gfs-analysis": "#84b6d8",
  "dynamical-hrrr-analysis": "#d4a875",
  "dynamical-mrms-analysis": "#d98276",
  "dynamical-imerg-late": "#b99bd8",
};

function dynamicalFillLayerId(datasetId: DynamicalDatasetId): string {
  return `${datasetId}-coverage-fill`;
}

function dynamicalLineLayerId(datasetId: DynamicalDatasetId): string {
  return `${datasetId}-coverage-line`;
}

function dynamicalRenderSourceId(datasetId: DynamicalDatasetId): string {
  return `${DYNAMICAL_RENDER_SOURCE_PREFIX}${datasetId}`;
}

function dynamicalRenderLayerIds(datasetId: DynamicalDatasetId): string[] {
  const prefix = `${DYNAMICAL_RENDER_LAYER_PREFIX}${datasetId}`;
  return [`${prefix}:image`, `${prefix}:fill`, `${prefix}:line`, `${prefix}:point`];
}

function emptyDynamicalRenderStates(): Record<DynamicalDatasetId, DynamicalRenderState> {
  return Object.fromEntries(
    DYNAMICAL_DATASETS.map((dataset) => [
      dataset.id,
      {
        phase: "idle",
        detail: "Enable the layer to request a viewport render.",
        kind: null,
        variable: null,
        units: null,
        validTime: null,
        generatedAt: null,
        attribution: null,
      } satisfies DynamicalRenderState,
    ]),
  ) as Record<DynamicalDatasetId, DynamicalRenderState>;
}

function removeDynamicalRender(map: MapLibreMap, datasetId: DynamicalDatasetId) {
  for (const layerId of dynamicalRenderLayerIds(datasetId)) {
    if (map.getLayer(layerId)) map.removeLayer(layerId);
  }
  const sourceId = dynamicalRenderSourceId(datasetId);
  if (map.getSource(sourceId)) map.removeSource(sourceId);
}

function addDynamicalRender(
  map: MapLibreMap,
  datasetId: DynamicalDatasetId,
  manifest: DynamicalRenderManifest,
  opacity: number,
) {
  removeDynamicalRender(map, datasetId);
  const sourceId = dynamicalRenderSourceId(datasetId);
  const [imageLayerId, fillLayerId, lineLayerId, pointLayerId] =
    dynamicalRenderLayerIds(datasetId);
  const beforeLayerId = DYNAMICAL_DATASETS
    .map((dataset) => dynamicalFillLayerId(dataset.id))
    .find((layerId) => map.getLayer(layerId));
  if (manifest.kind === "image") {
    const coordinates = manifest.coordinates.map(
      ([longitude, latitude]) => [longitude, latitude] as [number, number],
    ) as [[number, number], [number, number], [number, number], [number, number]];
    map.addSource(sourceId, {
      type: "image",
      url: manifest.url,
      coordinates,
    });
    map.addLayer({
      id: imageLayerId,
      type: "raster",
      source: sourceId,
      paint: {
        "raster-opacity": opacity,
        "raster-fade-duration": 120,
        "raster-resampling": "linear",
      },
    }, beforeLayerId);
    return;
  }
  map.addSource(sourceId, {
    type: "geojson",
    data: manifest.data as Parameters<GeoJSONSource["setData"]>[0],
    attribution: "Derived Dynamical analysis; see the Activity render metadata.",
  });
  map.addLayer({
    id: fillLayerId,
    type: "fill",
    source: sourceId,
    filter: ["==", ["geometry-type"], "Polygon"],
    paint: {
      "fill-color": DYNAMICAL_COLORS[datasetId],
      "fill-opacity": opacity * 0.58,
    },
  }, beforeLayerId);
  map.addLayer({
    id: lineLayerId,
    type: "line",
    source: sourceId,
    filter: ["==", ["geometry-type"], "LineString"],
    paint: {
      "line-color": DYNAMICAL_COLORS[datasetId],
      "line-opacity": opacity,
      "line-width": 2.2,
    },
  }, beforeLayerId);
  map.addLayer({
    id: pointLayerId,
    type: "circle",
    source: sourceId,
    filter: ["==", ["geometry-type"], "Point"],
    paint: {
      "circle-color": DYNAMICAL_COLORS[datasetId],
      "circle-opacity": opacity,
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 3, 10, 7],
      "circle-stroke-color": "#071311",
      "circle-stroke-width": 1,
    },
  }, beforeLayerId);
}

function readAnalysisLayerVisibility(): AnalysisLayerVisibility {
  if (typeof window === "undefined") {
    return { enabled: true, hiddenLayerIds: [] };
  }
  try {
    const candidate = JSON.parse(
      window.sessionStorage.getItem(ANALYSIS_VISIBILITY_STORAGE_KEY) ?? "null",
    ) as unknown;
    if (
      typeof candidate === "object" &&
      candidate !== null &&
      "enabled" in candidate &&
      typeof candidate.enabled === "boolean" &&
      "hiddenLayerIds" in candidate &&
      Array.isArray(candidate.hiddenLayerIds)
    ) {
      return {
        enabled: candidate.enabled,
        hiddenLayerIds: candidate.hiddenLayerIds
          .filter((layerId): layerId is string => typeof layerId === "string")
          .slice(0, 64),
      };
    }
  } catch {
    // A damaged session preference should never block the map.
  }
  return { enabled: true, hiddenLayerIds: [] };
}

function publicReportCollection(
  reports: readonly PublicReportRecord[],
) {
  return {
    type: "FeatureCollection" as const,
    features: reports.map((report) => ({
      type: "Feature" as const,
      id: report.reportId,
      geometry: {
        type: "Point" as const,
        coordinates: [report.longitude, report.latitude],
      },
      properties: {
        id: report.reportId,
        title: report.title,
        locationName: report.locationName,
        observedAt: report.observedAt,
        observedYear: report.observedYear,
        coordinatePrecision: report.coordinatePrecision ?? "",
        sourceKey: report.sourceKey,
        sourceName: report.sourceName,
        sourceUrl: report.sourceUrl ?? "",
        publishedAt: report.publishedAt ?? "",
        indexedAt: report.indexedAt ?? "",
        summary: report.summary,
        status: report.status,
        qualityScore: report.qualityScore,
        reportClass: report.reportClass,
      },
    })),
  };
}

function isSidequestEligibleReport(report: PublicReportRecord): boolean {
  return (
    report.sourceKey === "ufosint" &&
    report.status === "unverified" &&
    report.reportClass === "current-index" &&
    report.indexedAt !== null &&
    Number.isInteger(report.qualityScore) &&
    report.qualityScore >= 51 &&
    report.qualityScore <= 100
  );
}

function facilityCollection(locations: readonly PublicLocation[], selectedId: string) {
  return {
    type: "FeatureCollection" as const,
    features: locations.flatMap((location, index) => {
      const coordinate = facilityMapCoordinate(location);
      if (!coordinate) return [];
      return [{
        type: "Feature" as const,
        id: location.id,
        geometry: {
          type: "Point" as const,
          coordinates: [coordinate.longitude, coordinate.latitude],
        },
        properties: {
          id: location.id,
          index: String(index + 1).padStart(2, "0"),
          name: location.name,
          shortName: location.shortName,
          sector: coordinate.label,
          status: location.status,
          selected: location.id === selectedId,
          precisionKm: coordinate.precisionKm,
        },
      }];
    }),
  };
}

function trajectoryCollection(layers: readonly PublicAnomalyMapLayer[]) {
  return {
    type: "FeatureCollection" as const,
    features: layers.flatMap((layer) => {
      if (layer.kind !== "trajectory" || layer.samples.length < 2) return [];
      const uncertainties = layer.samples.map((sample) =>
        Math.max(0, sample.uncertaintyKm),
      );
      return [{
        type: "Feature" as const,
        geometry: {
          type: "LineString" as const,
          coordinates: layer.samples.map((sample) => [
            sample.longitude,
            sample.latitude,
          ]),
        },
        properties: {
          id: layer.layerId,
          label: layer.label,
          observations: layer.samples.length,
          meanUncertaintyKm:
            uncertainties.reduce((total, value) => total + value, 0) /
            uncertainties.length,
          maximumUncertaintyKm: Math.max(...uncertainties),
          observedStart: layer.samples[0].observedAt,
          observedEnd: layer.samples[layer.samples.length - 1].observedAt,
        },
      }];
    }),
  };
}

function heatCollection(layers: readonly PublicAnomalyMapLayer[]) {
  return {
    type: "FeatureCollection" as const,
    features: layers.flatMap((layer) => {
      if (layer.kind !== "heatmap") return [];
      return layer.cells.map((cell) => ({
        type: "Feature" as const,
        geometry: {
          type: "Point" as const,
          coordinates: [cell.longitude, cell.latitude],
        },
        properties: {
          id: cell.cellId,
          label: layer.label,
          intensity: Math.min(1, Math.max(0, cell.intensity)),
          radiusKm: cell.radiusKm,
          references: cell.sourceReferences.length,
        },
      }));
    }),
  };
}

function setSourceData(map: MapLibreMap, sourceId: string, data: object) {
  (map.getSource(sourceId) as GeoJSONSource | undefined)?.setData(
    data as Parameters<GeoJSONSource["setData"]>[0],
  );
}

export function GeographicFieldMap({
  locations,
  anomalyLayers,
  selectedId,
  onSelect,
  sessionToken: _sessionToken = null,
  initialSidequestReportId: _initialSidequestReportId = null,
  onSidequestReportIdChange: _onSidequestReportIdChange,
  participant: _participant = null,
  readOnly = false,
}: GeographicFieldMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const displayTriggerRef = useRef<HTMLButtonElement | null>(null);
  const displayDialogRef = useRef<HTMLDialogElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const publicReportsRef = useRef<PublicReportRecord[]>([]);
  const sidequestChangeRef = useRef(_onSidequestReportIdChange);
  const readOnlyRef = useRef(readOnly);
  const [analysisVisibility, setAnalysisVisibility] =
    useState<AnalysisLayerVisibility>(readAnalysisLayerVisibility);
  const visibleAnalysisLayers = useMemo(() => {
    if (!analysisVisibility.enabled) return [];
    const hidden = new Set(analysisVisibility.hiddenLayerIds);
    return anomalyLayers.filter((layer) => !hidden.has(layer.layerId));
  }, [analysisVisibility, anomalyLayers]);
  const propsRef = useRef({
    locations,
    anomalyLayers: visibleAnalysisLayers,
    selectedId,
    onSelect,
  });
  const settingsRef = useRef<ExternalLayerSettings>(DEFAULT_EXTERNAL_SETTINGS);
  const [mapError, setMapError] = useState<string | null>(null);
  const [externalSettings, setExternalSettings] = useState<ExternalLayerSettings>(
    DEFAULT_EXTERNAL_SETTINGS,
  );
  const [dynamicalRenderStates, setDynamicalRenderStates] =
    useState<Record<DynamicalDatasetId, DynamicalRenderState>>(
      emptyDynamicalRenderStates,
    );
  const [dynamicalRenderRefresh, setDynamicalRenderRefresh] = useState(0);
  const [alertStatus, setAlertStatus] = useState("Not requested");
  const [alertCount, setAlertCount] = useState(0);
  const [alertRefresh, setAlertRefresh] = useState(0);
  const [publicReports, setPublicReports] = useState<PublicReportRecord[]>([]);
  const [reportStatus, setReportStatus] = useState("Not requested");
  const [reportYearExtent, setReportYearExtent] = useState<[number, number]>([1940, 2002]);
  const [reportEndYear, setReportEndYear] = useState(2002);
  const [reportWindowYears, setReportWindowYears] = useState(5);
  const [reportSourceFilter, setReportSourceFilter] = useState("all");
  const [reportSearch, setReportSearch] = useState("");
  const [reportMinimumQuality, setReportMinimumQuality] = useState(51);
  const [reportCurrentOnly, setReportCurrentOnly] = useState(false);
  const sidequestReportId = !readOnly && /^ufosint:[1-9][0-9]{0,18}$/u.test(
    _initialSidequestReportId ?? "",
  )
    ? _initialSidequestReportId
    : null;
  const invalidSidequestReportId = Boolean(
    !readOnly && _initialSidequestReportId && sidequestReportId === null,
  );
  const selectedSidequestReport = useMemo(
    () =>
      sidequestReportId
        ? publicReports.find((report) => report.reportId === sidequestReportId) ?? null
        : null,
    [publicReports, sidequestReportId],
  );
  const satelliteDate = latestCompleteUtcDate();
  const alertsVisible = externalSettings["nws-alerts"].visible;
  const reportsVisible = externalSettings["uap-public-reports"].visible;
  const activeDynamicalDatasetIds = useMemo(
    () =>
      DYNAMICAL_DATASETS
        .filter((dataset) => externalSettings[dataset.id].visible)
        .map((dataset) => dataset.id),
    [externalSettings],
  );
  const activeDynamicalDatasetKey = activeDynamicalDatasetIds.join(",");
  const dynamicalContextVisible = activeDynamicalDatasetIds.length > 0;
  const reportDataNeeded = reportsVisible || dynamicalContextVisible;
  propsRef.current = {
    locations,
    anomalyLayers: visibleAnalysisLayers,
    selectedId,
    onSelect,
  };
  settingsRef.current = externalSettings;
  publicReportsRef.current = publicReports;
  sidequestChangeRef.current = _onSidequestReportIdChange;
  readOnlyRef.current = readOnly;

  useEffect(() => {
    if (!sidequestReportId) {
      return;
    }
    setExternalSettings((current) => ({
      ...current,
      "uap-public-reports": {
        ...current["uap-public-reports"],
        visible: true,
      },
    }));
    setReportSourceFilter("ufosint");
    setReportCurrentOnly(true);
  }, [sidequestReportId]);

  useEffect(() => {
    if (selectedSidequestReport) {
      setReportEndYear(selectedSidequestReport.observedYear);
    }
  }, [selectedSidequestReport]);

  useEffect(() => {
    try {
      window.sessionStorage.setItem(
        ANALYSIS_VISIBILITY_STORAGE_KEY,
        JSON.stringify(analysisVisibility),
      );
    } catch {
      // Visibility still works when session storage is unavailable.
    }
  }, [analysisVisibility]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const tileUrl =
      import.meta.env.VITE_MAP_TILE_URL?.trim() ||
      "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
    const cartoTiles = new URL(tileUrl, window.location.href).hostname.endsWith(
      ".basemaps.cartocdn.com",
    );
    const map = new maplibregl.Map({
      container: containerRef.current,
      center: [-98.4, 39.5],
      zoom: 2.75,
      minZoom: 1.5,
      maxZoom: 16,
      pixelRatio: window.matchMedia("(pointer: coarse)").matches
        ? Math.min(window.devicePixelRatio, 1.5)
        : window.devicePixelRatio,
      // The map lives inside a scrolling Activity on every platform. Keep
      // ordinary page gestures available even when an embedded WebView
      // misreports its pointer type.
      cooperativeGestures: false,
      renderWorldCopies: false,
      attributionControl: false,
      style: {
        version: 8,
        sources: {
          "openstreetmap-raster": {
            type: "raster",
            tiles: [tileUrl],
            tileSize: 256,
            attribution:
              '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a>' +
              (cartoTiles
                ? ' © <a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer">CARTO</a>'
                : ""),
          },
        },
        layers: [{
          id: "openstreetmap-raster",
          type: "raster",
          source: "openstreetmap-raster",
          paint: {
            "raster-saturation": cartoTiles ? -0.55 : -0.8,
            "raster-contrast": cartoTiles ? 0.16 : 0.08,
            "raster-brightness-min": cartoTiles ? 0.12 : 0.04,
            "raster-brightness-max": cartoTiles ? 0.82 : 0.42,
          },
        }],
      },
    });
    mapRef.current = map;
    map.dragPan.enable();
    map.scrollZoom.enable();
    map.touchZoomRotate.enable();
    const updateViewportDataset = () => {
      const container = containerRef.current;
      if (!container) return;
      const center = map.getCenter();
      container.dataset.mapZoom = map.getZoom().toFixed(3);
      container.dataset.mapLongitude = center.lng.toFixed(5);
      container.dataset.mapLatitude = center.lat.toFixed(5);
    };
    updateViewportDataset();
    map.on("moveend", updateViewportDataset);
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-left");
    map.addControl(new maplibregl.AttributionControl({ compact: false }), "bottom-right");
    map.on("error", (event) => {
      const sourceId = (event as unknown as { sourceId?: string }).sourceId;
      if (event.error && sourceId === "openstreetmap-raster") {
        setMapError("The basemap could not be loaded. Check the tile provider or network policy.");
      }
      if (event.error && sourceId?.startsWith(DYNAMICAL_RENDER_SOURCE_PREFIX)) {
        const datasetId = sourceId.slice(DYNAMICAL_RENDER_SOURCE_PREFIX.length);
        if (isDynamicalDatasetId(datasetId)) {
          setDynamicalRenderStates((current) => ({
            ...current,
            [datasetId]: {
              ...current[datasetId],
              phase: "error",
              detail: "The rendered image could not be loaded; catalog coverage remains visible.",
            },
          }));
        }
      }
    });

    map.on("load", () => {
      const current = propsRef.current;
      const settings = settingsRef.current;
      map.addSource(SATELLITE_SOURCE, {
        type: "raster",
        tiles: [nasaTrueColorTileUrl(satelliteDate)],
        tileSize: 256,
        maxzoom: 9,
        attribution:
          'Imagery: <a href="https://earthdata.nasa.gov/gibs" target="_blank" rel="noopener noreferrer">NASA GIBS</a>',
      });
      map.addLayer({
        id: SATELLITE_LAYER,
        type: "raster",
        source: SATELLITE_SOURCE,
        layout: {
          visibility: settings["nasa-true-color"].visible ? "visible" : "none",
        },
        paint: {
          "raster-opacity": settings["nasa-true-color"].opacity,
          "raster-fade-duration": 180,
        },
      });
      map.addSource(RADAR_SOURCE, {
        type: "raster",
        tiles: [NOAA_RADAR_TILE_URL],
        tileSize: 256,
        attribution:
          'Radar: <a href="https://radar.weather.gov/" target="_blank" rel="noopener noreferrer">NOAA/NWS</a>',
      });
      map.addLayer({
        id: RADAR_LAYER,
        type: "raster",
        source: RADAR_SOURCE,
        layout: {
          visibility: settings["noaa-radar"].visible ? "visible" : "none",
        },
        paint: {
          "raster-opacity": settings["noaa-radar"].opacity,
          "raster-fade-duration": 100,
        },
      });
      map.addSource(ALERT_SOURCE, {
        type: "geojson",
        data: EMPTY_COLLECTION,
        attribution:
          'Alerts: <a href="https://www.weather.gov/documentation/services-web-alerts" target="_blank" rel="noopener noreferrer">NOAA/NWS</a>',
      });
      map.addLayer({
        id: ALERT_FILL_LAYER,
        type: "fill",
        source: ALERT_SOURCE,
        layout: {
          visibility: settings["nws-alerts"].visible ? "visible" : "none",
        },
        paint: {
          "fill-color": [
            "match", ["get", "severity"],
            "Extreme", "#d74242",
            "Severe", "#ef7d43",
            "Moderate", "#edc66b",
            "Minor", "#76bfc3",
            "#9d8abb",
          ],
          "fill-opacity": settings["nws-alerts"].opacity,
        },
      });
      map.addLayer({
        id: ALERT_LINE_LAYER,
        type: "line",
        source: ALERT_SOURCE,
        layout: {
          visibility: settings["nws-alerts"].visible ? "visible" : "none",
        },
        paint: {
          "line-color": "#fff1d1",
          "line-opacity": Math.min(1, settings["nws-alerts"].opacity + 0.3),
          "line-width": 1.4,
          "line-dasharray": [2, 1],
        },
      });
      map.addSource(REPORT_SOURCE, {
        type: "geojson",
        data: EMPTY_COLLECTION,
        attribution:
          'Historical reports: <a href="https://www.uapdrop.com/data.html" target="_blank" rel="noopener noreferrer">UAPDrop</a> (CC BY 4.0). Current index: <a href="https://ufosint.com/" target="_blank" rel="noopener noreferrer">UFOSINT Explorer</a>; structured derived fields only, quality score above 50.',
      });
      map.addLayer({
        id: REPORT_POINT_LAYER,
        type: "circle",
        source: REPORT_SOURCE,
        layout: {
          visibility: settings["uap-public-reports"].visible ? "visible" : "none",
        },
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 6, 8, 10],
          "circle-color": [
            "case",
            ["==", ["get", "reportClass"], "current-index"], "#f2d27a",
            ["==", ["get", "reportClass"], "recently-published"], "#f2d27a",
            ["==", ["get", "reportClass"], "newly-published-historical"], "#b79ad6",
            [
              "interpolate", ["linear"], ["get", "observedYear"],
              1823, "#70847e",
              1945, "#75b6ba",
              1975, "#e0bd73",
              2003, "#db745a",
            ],
          ],
          "circle-opacity": settings["uap-public-reports"].opacity,
          "circle-stroke-color": "#071311",
          "circle-stroke-width": 1.2,
        },
      });
      map.addLayer({
        id: REPORT_HIT_LAYER,
        type: "circle",
        source: REPORT_SOURCE,
        layout: {
          visibility: settings["uap-public-reports"].visible ? "visible" : "none",
        },
        paint: {
          // A nearly transparent 40px target keeps crowded report dots tappable.
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 20, 8, 22],
          "circle-color": "#ffffff",
          "circle-opacity": 0.001,
          "circle-stroke-opacity": 0,
        },
      });
      map.addSource(DYNAMICAL_SOURCE, {
        type: "geojson",
        data: dynamicalCoverageCollection(),
        attribution:
          'Historical-weather datasets: <a href="https://dynamical.org/catalog/" target="_blank" rel="noopener noreferrer">Dynamical</a>; per-dataset license and limitations apply.',
      });
      for (const [index, dataset] of DYNAMICAL_DATASETS.entries()) {
        const setting = settings[dataset.id];
        const visibility = setting.visible ? "visible" : "none";
        map.addLayer({
          id: dynamicalFillLayerId(dataset.id),
          type: "fill",
          source: DYNAMICAL_SOURCE,
          filter: ["==", ["get", "id"], dataset.id],
          layout: { visibility },
          paint: {
            "fill-color": DYNAMICAL_COLORS[dataset.id],
            "fill-opacity": setting.opacity * 0.22,
          },
        });
        map.addLayer({
          id: dynamicalLineLayerId(dataset.id),
          type: "line",
          source: DYNAMICAL_SOURCE,
          filter: ["==", ["get", "id"], dataset.id],
          layout: { visibility },
          paint: {
            "line-color": DYNAMICAL_COLORS[dataset.id],
            "line-opacity": setting.opacity,
            "line-width": 2.1 + (index % 2) * 0.55,
            "line-dasharray": index % 2 === 0 ? [2, 1.5] : [1, 2],
          },
        });
      }
      map.addSource(DYNAMICAL_CONTEXT_SOURCE, {
        type: "geojson",
        data: EMPTY_COLLECTION,
        attribution:
          "Dynamical query-compatible report windows; these markers are not meteorological observations.",
      });
      map.addSource(HEAT_SOURCE, {
        type: "geojson",
        data: heatCollection(current.anomalyLayers),
      });
      map.addLayer({
        id: "uniflora-heat",
        type: "heatmap",
        source: HEAT_SOURCE,
        maxzoom: 12,
        paint: {
          "heatmap-weight": ["get", "intensity"],
          "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 2, 1.15, 10, 2.8],
          "heatmap-radius": [
            "interpolate",
            ["linear"],
            ["zoom"],
            2,
            [
              "interpolate",
              ["linear"],
              ["get", "radiusKm"],
              8,
              12,
              2_500,
              44,
            ],
            10,
            [
              "interpolate",
              ["linear"],
              ["get", "radiusKm"],
              8,
              24,
              2_500,
              92,
            ],
          ],
          "heatmap-opacity": 0.84,
          "heatmap-color": [
            "interpolate", ["linear"], ["heatmap-density"],
            0, "rgba(16,28,27,0)",
            0.3, "rgba(66,156,162,0.5)",
            0.62, "rgba(226,190,109,0.78)",
            1, "rgba(221,91,61,0.92)",
          ],
        },
      });
      map.addSource(TRAJECTORY_SOURCE, {
        type: "geojson",
        data: trajectoryCollection(current.anomalyLayers),
      });
      map.addLayer({
        id: "uniflora-trajectory-halo",
        type: "line",
        source: TRAJECTORY_SOURCE,
        paint: {
          "line-color": "#183c42",
          "line-width": [
            "interpolate",
            ["linear"],
            ["get", "meanUncertaintyKm"],
            0,
            6,
            50,
            13,
            500,
            24,
          ],
          "line-opacity": [
            "interpolate",
            ["linear"],
            ["get", "meanUncertaintyKm"],
            0,
            0.38,
            500,
            0.7,
          ],
        },
      });
      map.addLayer({
        id: "uniflora-trajectory",
        type: "line",
        source: TRAJECTORY_SOURCE,
        paint: {
          "line-color": "#f1c77d",
          "line-width": 3,
          "line-opacity": 0.92,
          "line-dasharray": [1.2, 0.7],
        },
      });
      map.addLayer({
        id: DYNAMICAL_CONTEXT_LAYER,
        type: "circle",
        source: DYNAMICAL_CONTEXT_SOURCE,
        layout: {
          visibility: DYNAMICAL_DATASETS.some(
            (dataset) => settings[dataset.id].visible,
          )
            ? "visible"
            : "none",
        },
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 3.5, 8, 7.5],
          "circle-color": [
            "interpolate",
            ["linear"],
            ["get", "datasetCount"],
            1,
            "#84b6d8",
            3,
            "#f1c77d",
            5,
            "#d98276",
          ],
          "circle-opacity": 0.9,
          "circle-stroke-color": "#071311",
          "circle-stroke-width": 1.2,
        },
      });
      map.addSource(FACILITY_SOURCE, {
        type: "geojson",
        data: facilityCollection(current.locations, current.selectedId),
      });
      map.addLayer({
        id: "uniflora-facility-uncertainty",
        type: "circle",
        source: FACILITY_SOURCE,
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 2, 14, 9, 42],
          "circle-color": "#5eb0b2",
          "circle-opacity": 0.12,
          "circle-stroke-color": "#8bc8ca",
          "circle-stroke-opacity": 0.22,
          "circle-stroke-width": 1,
        },
      });
      map.addLayer({
        id: "uniflora-facility-points",
        type: "circle",
        source: FACILITY_SOURCE,
        paint: {
          "circle-radius": ["case", ["get", "selected"], 8, ["==", ["get", "status"], "focus"], 7, 5],
          "circle-color": [
            "match", ["get", "status"],
            "focus", "#f1c77d",
            "available", "#77c0c2",
            "#6c7470",
          ],
          "circle-stroke-color": "#071311",
          "circle-stroke-width": ["case", ["get", "selected"], 3, 2],
          "circle-opacity": ["case", ["==", ["get", "status"], "locked"], 0.7, 1],
        },
      });
      map.addLayer({
        id: "uniflora-facility-labels",
        type: "symbol",
        source: FACILITY_SOURCE,
        layout: {
          "text-field": ["concat", ["get", "index"], "  ", ["get", "shortName"]],
          "text-size": 11,
          "text-anchor": "left",
          "text-offset": [0.9, 0],
          "text-allow-overlap": false,
        },
        paint: {
          "text-color": "#eef1e9",
          "text-halo-color": "#071311",
          "text-halo-width": 2,
          "text-halo-blur": 1,
        },
      });

      const selectFacility = (event: MapMouseEvent) => {
        const feature = map.queryRenderedFeatures(event.point, {
          layers: ["uniflora-facility-points"],
        })[0];
        const id = feature?.properties?.id;
        if (typeof id === "string") propsRef.current.onSelect(id);
      };
      map.on("click", "uniflora-facility-points", selectFacility);
      map.on("mouseenter", "uniflora-facility-points", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "uniflora-facility-points", () => {
        map.getCanvas().style.cursor = "";
      });
      map.on("click", ALERT_FILL_LAYER, (event) => {
        const feature = event.features?.[0];
        if (!feature?.properties) return;
        const content = document.createElement("article");
        content.className = "weather-alert-popup";
        const heading = document.createElement("strong");
        heading.textContent = String(feature.properties.event || "Active weather alert");
        const headline = document.createElement("p");
        headline.textContent = String(feature.properties.headline || "");
        const metadata = document.createElement("small");
        metadata.textContent = [
          feature.properties.severity,
          feature.properties.urgency,
          feature.properties.expires
            ? `expires ${feature.properties.expires}`
            : "",
        ].filter(Boolean).join(" · ");
        content.append(heading, headline, metadata);
        new maplibregl.Popup({ maxWidth: "360px" })
          .setLngLat(event.lngLat)
          .setDOMContent(content)
          .addTo(map);
      });
      map.on("click", REPORT_HIT_LAYER, (event) => {
        const feature = event.features?.[0];
        if (!feature?.properties) return;
        const content = document.createElement("article");
        content.className = "public-report-popup";
        const heading = document.createElement("strong");
        heading.textContent = String(feature.properties.title || "Public report");
        const metadata = document.createElement("p");
        const observed = new Date(String(feature.properties.observedAt));
        metadata.textContent = [
          Number.isNaN(observed.valueOf()) ? "" : observed.toLocaleDateString(),
          feature.properties.locationName,
          feature.properties.coordinatePrecision,
        ].filter(Boolean).join(" · ");
        const summaryText = String(feature.properties.summary || "");
        const summaryHeading = document.createElement("small");
        summaryHeading.textContent =
          feature.properties.sourceKey === "ufosint"
            ? "Witness summary"
            : "Report summary";
        const summary = document.createElement("p");
        summary.textContent = summaryText;
        const published = new Date(String(feature.properties.publishedAt || ""));
        const indexed = new Date(String(feature.properties.indexedAt || ""));
        const qualityScore = Number(feature.properties.qualityScore || 0);
        const classification = document.createElement("small");
        classification.textContent = [
          feature.properties.reportClass === "current-index"
            ? "UFOSINT current index"
            : feature.properties.reportClass === "recently-published"
              ? "Recently published current-event report"
              : feature.properties.reportClass === "newly-published-historical"
                ? "Newly published historical report"
                : "Historical archive report",
          feature.properties.status,
          feature.properties.reportClass === "current-index" && qualityScore >= 51
            ? `quality ${qualityScore}/100`
            : "",
          Number.isNaN(indexed.valueOf())
            ? ""
            : `indexed ${indexed.toLocaleString()}`,
          Number.isNaN(published.valueOf())
            ? ""
            : `published ${published.toLocaleDateString()}`,
          "Unverified external index record; no progression effect",
        ].filter(Boolean).join(" · ");
        const sourceUrl = String(feature.properties.sourceUrl || "");
        const source = sourceUrl ? document.createElement("a") : document.createElement("small");
        source.textContent = `Source: ${String(feature.properties.sourceName || feature.properties.sourceKey || "archive")}`;
        if (source instanceof HTMLAnchorElement) {
          source.href = sourceUrl;
          source.target = "_blank";
          source.rel = "noopener noreferrer";
        }
        content.append(heading, metadata);
        if (summaryText) content.append(summaryHeading, summary);
        content.append(classification, source);
        const reportId = String(feature.properties?.id ?? "");
        const report = publicReportsRef.current.find(
          (candidate) => candidate.reportId === reportId,
        );
        if (!readOnlyRef.current && report && isSidequestEligibleReport(report)) {
          const investigate = document.createElement("button");
          investigate.type = "button";
          investigate.className = "public-report-sidequest-launch";
          investigate.textContent = "Investigate as sidequest";
          investigate.addEventListener("click", () => {
            sidequestChangeRef.current(report.reportId);
          });
          content.append(investigate);
        }
        new maplibregl.Popup({ maxWidth: "340px" })
          .setLngLat(event.lngLat)
          .setDOMContent(content)
          .addTo(map);
      });
      map.on("mouseenter", REPORT_HIT_LAYER, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", REPORT_HIT_LAYER, () => {
        map.getCanvas().style.cursor = "";
      });
      for (const dataset of DYNAMICAL_DATASETS) {
        const fillLayerId = dynamicalFillLayerId(dataset.id);
        map.on("click", fillLayerId, (event) => {
          const content = document.createElement("article");
          content.className = "dynamical-dataset-popup";
          const heading = document.createElement("strong");
          heading.textContent = dataset.label;
          const scope = document.createElement("p");
          scope.textContent = [
            dataset.spatialDomain,
            dataset.spatialResolution,
            dataset.temporalResolution,
            `from ${dataset.temporalStart.slice(0, 10)}`,
          ].join(" · ");
          const variables = document.createElement("p");
          variables.textContent = `Evidence fields: ${dataset.variables.join(", ")}.`;
          const limitation = document.createElement("small");
          limitation.textContent = dataset.limitation;
          const source = document.createElement("a");
          source.href = dataset.sourceUrl;
          source.target = "_blank";
          source.rel = "noopener noreferrer";
          source.textContent = `Open ${dataset.shortLabel} catalog · ${dataset.license}`;
          content.append(heading, scope, variables, limitation, source);
          new maplibregl.Popup({ maxWidth: "360px" })
            .setLngLat(event.lngLat)
            .setDOMContent(content)
            .addTo(map);
        });
        map.on("mouseenter", fillLayerId, () => {
          map.getCanvas().style.cursor = "help";
        });
        map.on("mouseleave", fillLayerId, () => {
          map.getCanvas().style.cursor = "";
        });
      }
      map.on("click", DYNAMICAL_CONTEXT_LAYER, (event) => {
        const properties = event.features?.[0]?.properties;
        if (!properties) return;
        const reportId = String(properties.reportId ?? "");
        const datasetIds = String(properties.datasetIds ?? "")
          .split(",")
          .filter(Boolean);
        const enabledDatasets = DYNAMICAL_DATASETS.filter(
          (dataset) =>
            datasetIds.includes(dataset.id) &&
            settingsRef.current[dataset.id].visible,
        );
        const content = document.createElement("article");
        content.className = "dynamical-dataset-popup";
        const heading = document.createElement("strong");
        heading.textContent = "Dynamical query-compatible report window";
        const reportSummary = document.createElement("p");
        const observed = new Date(String(properties.observedAt ?? ""));
        reportSummary.textContent = [
          String(properties.title ?? "Public report"),
          String(properties.locationName ?? ""),
          Number.isNaN(observed.valueOf()) ? "" : observed.toLocaleDateString(),
        ].filter(Boolean).join(" · ");
        const explanation = document.createElement("small");
        explanation.textContent =
          "This marker means the report date and privacy-reduced location intersect the enabled catalog coverage. It is not a weather observation.";
        const datasetList = document.createElement("ul");
        for (const dataset of enabledDatasets) {
          const item = document.createElement("li");
          const source = document.createElement("a");
          source.href = dataset.sourceUrl;
          source.target = "_blank";
          source.rel = "noopener noreferrer";
          source.textContent = dataset.shortLabel;
          item.append(source);
          datasetList.append(item);
        }
        content.append(heading, reportSummary, explanation, datasetList);
        const report = publicReportsRef.current.find(
          (candidate) => candidate.reportId === reportId,
        );
        if (!readOnlyRef.current && report && isSidequestEligibleReport(report)) {
          const investigate = document.createElement("button");
          investigate.type = "button";
          investigate.className = "public-report-sidequest-launch";
          investigate.textContent = "Open report sidequest";
          investigate.addEventListener("click", () => {
            sidequestChangeRef.current(report.reportId);
          });
          content.append(investigate);
        }
        new maplibregl.Popup({ maxWidth: "360px" })
          .setLngLat(event.lngLat)
          .setDOMContent(content)
          .addTo(map);
      });
      map.on("mouseenter", DYNAMICAL_CONTEXT_LAYER, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", DYNAMICAL_CONTEXT_LAYER, () => {
        map.getCanvas().style.cursor = "";
      });
    });

    return () => {
      map.off("moveend", updateViewportDataset);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded()) return;
    setSourceData(map, FACILITY_SOURCE, facilityCollection(locations, selectedId));
    setSourceData(
      map,
      TRAJECTORY_SOURCE,
      trajectoryCollection(visibleAnalysisLayers),
    );
    setSourceData(map, HEAT_SOURCE, heatCollection(visibleAnalysisLayers));
  }, [locations, selectedId, visibleAnalysisLayers]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded()) return;
    const visibility = (visible: boolean) => visible ? "visible" : "none";
    map.setLayoutProperty(
      SATELLITE_LAYER,
      "visibility",
      visibility(externalSettings["nasa-true-color"].visible),
    );
    map.setPaintProperty(
      SATELLITE_LAYER,
      "raster-opacity",
      externalSettings["nasa-true-color"].opacity,
    );
    map.setLayoutProperty(
      RADAR_LAYER,
      "visibility",
      visibility(externalSettings["noaa-radar"].visible),
    );
    map.setPaintProperty(
      RADAR_LAYER,
      "raster-opacity",
      externalSettings["noaa-radar"].opacity,
    );
    for (const layerId of [ALERT_FILL_LAYER, ALERT_LINE_LAYER]) {
      map.setLayoutProperty(
        layerId,
        "visibility",
        visibility(externalSettings["nws-alerts"].visible),
      );
    }
    map.setPaintProperty(
      ALERT_FILL_LAYER,
      "fill-opacity",
      externalSettings["nws-alerts"].opacity,
    );
    map.setPaintProperty(
      ALERT_LINE_LAYER,
      "line-opacity",
      Math.min(1, externalSettings["nws-alerts"].opacity + 0.3),
    );
    map.setLayoutProperty(
      REPORT_POINT_LAYER,
      "visibility",
      visibility(externalSettings["uap-public-reports"].visible),
    );
    map.setLayoutProperty(
      REPORT_HIT_LAYER,
      "visibility",
      visibility(externalSettings["uap-public-reports"].visible),
    );
    map.setPaintProperty(
      REPORT_POINT_LAYER,
      "circle-opacity",
      externalSettings["uap-public-reports"].opacity,
    );
    for (const dataset of DYNAMICAL_DATASETS) {
      const setting = externalSettings[dataset.id];
      const datasetVisibility = visibility(setting.visible);
      map.setLayoutProperty(
        dynamicalFillLayerId(dataset.id),
        "visibility",
        datasetVisibility,
      );
      map.setLayoutProperty(
        dynamicalLineLayerId(dataset.id),
        "visibility",
        datasetVisibility,
      );
      map.setPaintProperty(
        dynamicalFillLayerId(dataset.id),
        "fill-opacity",
        dynamicalRenderStates[dataset.id].phase === "ready"
          ? 0
          : setting.opacity * 0.22,
      );
      map.setPaintProperty(
        dynamicalLineLayerId(dataset.id),
        "line-opacity",
        setting.opacity,
      );
      const [imageLayerId, fillLayerId, lineLayerId, pointLayerId] =
        dynamicalRenderLayerIds(dataset.id);
      for (const layerId of [imageLayerId, fillLayerId, lineLayerId, pointLayerId]) {
        if (map.getLayer(layerId)) {
          map.setLayoutProperty(layerId, "visibility", datasetVisibility);
        }
      }
      if (map.getLayer(imageLayerId)) {
        map.setPaintProperty(imageLayerId, "raster-opacity", setting.opacity);
      }
      if (map.getLayer(fillLayerId)) {
        map.setPaintProperty(fillLayerId, "fill-opacity", setting.opacity * 0.58);
      }
      if (map.getLayer(lineLayerId)) {
        map.setPaintProperty(lineLayerId, "line-opacity", setting.opacity);
      }
      if (map.getLayer(pointLayerId)) {
        map.setPaintProperty(pointLayerId, "circle-opacity", setting.opacity);
      }
    }
    map.setLayoutProperty(
      DYNAMICAL_CONTEXT_LAYER,
      "visibility",
      visibility(dynamicalContextVisible),
    );
    map.setPaintProperty(
      DYNAMICAL_CONTEXT_LAYER,
      "circle-opacity",
      activeDynamicalDatasetIds.length > 0
        ? Math.max(
            ...activeDynamicalDatasetIds.map(
              (datasetId) => externalSettings[datasetId].opacity,
            ),
          )
        : 0,
    );
  }, [
    activeDynamicalDatasetIds,
    dynamicalContextVisible,
    dynamicalRenderStates,
    externalSettings,
  ]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const datasetIds = activeDynamicalDatasetKey
      .split(",")
      .filter(isDynamicalDatasetId);
    if (datasetIds.length === 0) return;

    let requestController: AbortController | null = null;
    let refreshTimer: number | null = null;
    let generation = 0;
    const renderTime = selectedSidequestReport?.observedAt ?? null;

    const loadViewportRenders = async () => {
      if (!map.isStyleLoaded()) return;
      requestController?.abort();
      requestController = new AbortController();
      const signal = requestController.signal;
      const currentGeneration = ++generation;
      const bounds = map.getBounds();
      let west = Math.max(-180, bounds.getWest());
      let east = Math.min(180, bounds.getEast());
      if (west >= east) {
        west = -180;
        east = 180;
      }
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);
      const container = map.getContainer();
      const width = container.clientWidth * pixelRatio;
      const height = container.clientHeight * pixelRatio;

      setDynamicalRenderStates((current) => {
        const next = { ...current };
        for (const datasetId of datasetIds) {
          next[datasetId] = {
            ...current[datasetId],
            phase: "loading",
            detail: current[datasetId].kind
              ? "Refreshing this viewport…"
              : "Rendering this viewport…",
          };
        }
        return next;
      });

      await Promise.all(datasetIds.map(async (datasetId) => {
        try {
          const url = dynamicalRenderManifestUrl({
            datasetId,
            bbox: [west, bounds.getSouth(), east, bounds.getNorth()],
            width,
            height,
            time: renderTime,
          });
          const response = await fetch(url, {
            headers: { Accept: "application/json" },
            cache: "no-store",
            signal,
          });
          if (!response.ok) {
            const detail = response.status === 404
              ? "The map renderer is not deployed; catalog coverage remains visible."
              : response.status === 422
                ? "No render is available for this viewport or time."
                : `The map renderer returned ${response.status}.`;
            throw new Error(detail);
          }
          const body = await response.text();
          if (body.length > 8_000_000) {
            throw new Error("The render manifest exceeded the eight-megabyte display limit.");
          }
          const manifest = parseDynamicalRenderManifest(
            JSON.parse(body) as unknown,
            datasetId,
            window.location.origin,
          );
          if (signal.aborted || currentGeneration !== generation || !map.isStyleLoaded()) {
            return;
          }
          addDynamicalRender(
            map,
            datasetId,
            manifest,
            settingsRef.current[datasetId].opacity,
          );
          setDynamicalRenderStates((current) => ({
            ...current,
            [datasetId]: {
              phase: "ready",
              detail: manifest.kind === "image"
                ? "HoloViews raster is visible on the basemap."
                : `${manifest.data.features.length.toLocaleString()} derived map features are visible.`,
              kind: manifest.kind,
              variable: manifest.variable,
              units: manifest.units,
              validTime: manifest.validTime,
              generatedAt: manifest.generatedAt,
              attribution: manifest.attribution,
            },
          }));
        } catch (error) {
          if (signal.aborted || currentGeneration !== generation) return;
          setDynamicalRenderStates((current) => ({
            ...current,
            [datasetId]: {
              ...current[datasetId],
              phase: "error",
              detail: error instanceof Error
                ? error.message.slice(0, 240)
                : "The viewport render is unavailable.",
            },
          }));
        }
      }));
    };

    const scheduleViewportRender = () => {
      if (refreshTimer !== null) window.clearTimeout(refreshTimer);
      refreshTimer = window.setTimeout(() => {
        refreshTimer = null;
        void loadViewportRenders();
      }, 450);
    };

    if (map.isStyleLoaded()) {
      scheduleViewportRender();
    } else {
      map.once("load", scheduleViewportRender);
    }
    map.on("moveend", scheduleViewportRender);
    map.on("resize", scheduleViewportRender);
    return () => {
      generation += 1;
      requestController?.abort();
      if (refreshTimer !== null) window.clearTimeout(refreshTimer);
      map.off("load", scheduleViewportRender);
      map.off("moveend", scheduleViewportRender);
      map.off("resize", scheduleViewportRender);
    };
  }, [
    activeDynamicalDatasetKey,
    dynamicalRenderRefresh,
    selectedSidequestReport?.observedAt,
  ]);

  useEffect(() => {
    if (!alertsVisible) return;
    const controller = new AbortController();

    const loadAlerts = async () => {
      const urls = nwsAlertUrls(locations);
      if (urls.length === 0) {
        setAlertStatus("No facility coordinates available");
        return;
      }
      setAlertStatus("Retrieving");
      try {
        const collections = await Promise.all(
          urls.map(async (url) => {
            const response = await fetch(url, {
              headers: { Accept: "application/geo+json" },
              signal: controller.signal,
            });
            if (!response.ok) {
              throw new Error(`NWS returned ${response.status}`);
            }
            const body = await response.text();
            if (body.length > 2_000_000) {
              throw new Error("NWS response exceeded the two-megabyte limit");
            }
            return sanitizeNwsAlertCollection(JSON.parse(body));
          }),
        );
        const features = collections
          .flatMap((collection) => collection.features)
          .filter(
            (feature, index, all) =>
              all.findIndex((candidate) => candidate.id === feature.id) === index,
          )
          .slice(0, 100);
        const map = mapRef.current;
        if (map) {
          setSourceData(map, ALERT_SOURCE, {
            type: "FeatureCollection",
            features,
          });
        }
        setAlertCount(features.length);
        setAlertStatus(`Updated ${new Date().toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        })}`);
      } catch (error) {
        if (controller.signal.aborted) return;
        setAlertStatus(error instanceof Error ? error.message : "Unavailable");
      }
    };

    void loadAlerts();
    const timer = window.setInterval(loadAlerts, 5 * 60 * 1_000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [alertsVisible, locations, alertRefresh]);

  useEffect(() => {
    if (!reportDataNeeded) return;
    const controller = new AbortController();
    const loadReports = async () => {
      setReportStatus(publicReports.length > 0 ? "Refreshing reports" : "Loading reports");
      try {
        const response = await fetch("/api/ufo-reports", {
          headers: { Accept: "application/json" },
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`Reports returned ${response.status}`);
        }
        const body = await response.text();
        if (body.length > 6_000_000) {
          throw new Error("Reports exceeded the six-megabyte display limit");
        }
        const snapshot = sanitizePublicReportSnapshot(JSON.parse(body));
        if (!snapshot) {
          throw new Error("Reports did not match the public report contract");
        }
        setPublicReports(snapshot.reports);
        setReportYearExtent([snapshot.startYear, snapshot.endYear]);
        setReportEndYear((current) =>
          current < snapshot.startYear || current > snapshot.endYear
            ? snapshot.endYear
            : Math.max(current, snapshot.endYear),
        );
        setReportStatus(
          `${snapshot.reports.length.toLocaleString()} records \u00b7 ${snapshot.license}`,
        );
      } catch (error) {
        if (controller.signal.aborted) return;
        setReportStatus(error instanceof Error ? error.message : "Reports unavailable");
      }
    };
    void loadReports();
    const timer = window.setInterval(loadReports, 5 * 60 * 1_000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [reportDataNeeded]);


  const filteredPublicReports = useMemo(() => {
    const startYear = reportEndYear - reportWindowYears + 1;
    const query = reportSearch.trim().toLocaleLowerCase();

    return publicReports.filter((report) => {
      if (
        report.observedYear < startYear ||
        report.observedYear > reportEndYear
      ) {
        return false;
      }
      if (
        reportSourceFilter === "ufosint" &&
        report.sourceKey !== "ufosint"
      ) {
        return false;
      }
      if (
        reportSourceFilter === "historical" &&
        report.sourceKey === "ufosint"
      ) {
        return false;
      }
      if (
        reportCurrentOnly &&
        report.reportClass !== "current-index"
      ) {
        return false;
      }
      if (
        report.sourceKey === "ufosint" &&
        Number(report.qualityScore ?? 0) < reportMinimumQuality
      ) {
        return false;
      }
      if (query) {
        const searchable = [
          report.title,
          report.locationName,
          report.summary,
          report.sourceName,
        ].join(" ").toLocaleLowerCase();
        if (!searchable.includes(query)) return false;
      }
      return true;
    });
  }, [
    publicReports,
    reportCurrentOnly,
    reportEndYear,
    reportMinimumQuality,
    reportSearch,
    reportSourceFilter,
    reportWindowYears,
  ]);

  const dynamicalReportContexts = useMemo(
    () => dynamicalReportContextCollection(filteredPublicReports),
    [filteredPublicReports],
  );
  const visibleDynamicalReportContexts = useMemo(() => {
    const enabled = new Set<string>(activeDynamicalDatasetIds);
    return {
      ...dynamicalReportContexts,
      features: dynamicalReportContexts.features.filter((feature) =>
        feature.properties.datasetIds
          .split(",")
          .some((datasetId) => enabled.has(datasetId)),
      ),
    };
  }, [activeDynamicalDatasetIds, dynamicalReportContexts]);
  const dynamicalContextCounts = useMemo(
    () =>
      Object.fromEntries(
        DYNAMICAL_DATASETS.map((dataset) => [
          dataset.id,
          dynamicalReportContexts.features.filter((feature) =>
            feature.properties.datasetIds.split(",").includes(dataset.id),
          ).length,
        ]),
      ) as Record<DynamicalDatasetId, number>,
    [dynamicalReportContexts],
  );

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded()) return;
    setSourceData(
      map,
      REPORT_SOURCE,
      publicReportCollection(filteredPublicReports),
    );
  }, [filteredPublicReports]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded()) return;
    setSourceData(
      map,
      DYNAMICAL_CONTEXT_SOURCE,
      visibleDynamicalReportContexts,
    );
  }, [visibleDynamicalReportContexts]);

  const visibleReportCount = filteredPublicReports.length;
  const keyboardSidequestReports = useMemo(
    () =>
      filteredPublicReports
        .filter(isSidequestEligibleReport)
        .slice(0, 25),
    [filteredPublicReports],
  );

  const updateExternalLayer = (
    layerId: ExternalMapLayerId,
    update: Partial<ExternalLayerSettings[ExternalMapLayerId]>,
  ) => {
    setExternalSettings((current) => ({
      ...current,
      [layerId]: { ...current[layerId], ...update },
    }));
  };

  const hideAllAnalysisLayers = () => {
    setAnalysisVisibility((current) => ({
      ...current,
      enabled: false,
    }));
  };

  const showAllAnalysisLayers = () => {
    setAnalysisVisibility({
      enabled: true,
      hiddenLayerIds: [],
    });
  };

  const setAnalysisLayerVisible = (layerId: string, visible: boolean) => {
    setAnalysisVisibility((current) => {
      if (visible && !current.enabled) {
        return {
          enabled: true,
          hiddenLayerIds: anomalyLayers
            .map((layer) => layer.layerId)
            .filter((candidate) => candidate !== layerId),
        };
      }
      const hidden = new Set(current.hiddenLayerIds);
      if (visible) hidden.delete(layerId);
      else hidden.add(layerId);
      return {
        enabled: true,
        hiddenLayerIds: [...hidden].slice(0, 64),
      };
    });
  };

  const openDisplayDialog = () => {
    const dialog = displayDialogRef.current;
    if (!dialog || dialog.open) return;
    dialog.showModal();
    window.requestAnimationFrame(() => {
      dialog.querySelector<HTMLElement>("[data-dialog-heading]")?.focus();
    });
  };

  const activeDynamicalRenderStates = activeDynamicalDatasetIds.map(
    (datasetId) => dynamicalRenderStates[datasetId],
  );
  const readyDynamicalRenderCount = activeDynamicalRenderStates.filter(
    (state) => state.phase === "ready",
  ).length;
  const loadingDynamicalRenderCount = activeDynamicalRenderStates.filter(
    (state) => state.phase === "loading",
  ).length;
  const dynamicalRenderSummary = loadingDynamicalRenderCount > 0
    ? `Rendering ${loadingDynamicalRenderCount} weather layer${loadingDynamicalRenderCount === 1 ? "" : "s"}…`
    : readyDynamicalRenderCount > 0
      ? `${readyDynamicalRenderCount}/${activeDynamicalRenderStates.length} weather render${activeDynamicalRenderStates.length === 1 ? "" : "s"} visible`
      : "Weather renderer unavailable · coverage fallback";

  return (
    <div className="geographic-field-map-shell">
      <div
        ref={containerRef}
        className="geographic-field-map"
        role="region"
        aria-label={`Interactive OpenStreetMap showing facility sectors and ${visibleAnalysisLayers.length} visible analysis layers`}
      />
      <button
        ref={displayTriggerRef}
        type="button"
        className="map-display-trigger"
        aria-haspopup="dialog"
        aria-controls="map-display-dialog"
        onClick={openDisplayDialog}
      >
        <span>Map display</span>
        <small aria-live="polite">
          {visibleAnalysisLayers.length}/{anomalyLayers.length} analysis
          {" Â· "}
          {Object.values(externalSettings).filter((layer) => layer.visible).length} reference
        </small>
      </button>
      {activeDynamicalRenderStates.length > 0 ? (
        <output
          className={`dynamical-render-readout${readyDynamicalRenderCount > 0 ? " ready" : ""}`}
          aria-live="polite"
        >
          {dynamicalRenderSummary}
        </output>
      ) : null}
      <dialog
        ref={displayDialogRef}
        id="map-display-dialog"
        className="map-display-dialog"
        aria-labelledby="map-display-dialog-title"
        aria-describedby="map-display-dialog-description"
        onClose={() => displayTriggerRef.current?.focus()}
      >
        <header className="map-display-dialog-header">
          <div>
            <p className="eyebrow">WGS84 Â· Web Mercator</p>
            <h3
              id="map-display-dialog-title"
              data-dialog-heading
              tabIndex={-1}
            >
              Map display
            </h3>
            <p id="map-display-dialog-description">
              Choose which analytical and reference overlays appear above the
              basemap. Facility sites remain visible.
            </p>
          </div>
          <form method="dialog">
            <button type="submit">Close</button>
          </form>
        </header>

        <section className="map-display-section" aria-labelledby="analysis-layer-heading">
          <header>
            <div>
              <p className="eyebrow">Laboratory output</p>
              <h4 id="analysis-layer-heading">Analysis layers</h4>
            </div>
            <strong>
              {visibleAnalysisLayers.length}/{anomalyLayers.length} visible
            </strong>
          </header>
          <div className="map-display-bulk-actions">
            <button
              type="button"
              onClick={showAllAnalysisLayers}
              disabled={
                analysisVisibility.enabled &&
                visibleAnalysisLayers.length === anomalyLayers.length
              }
            >
              Show all analysis
            </button>
            <button
              type="button"
              className="map-display-hide-all"
              onClick={hideAllAnalysisLayers}
              disabled={visibleAnalysisLayers.length === 0}
            >
              Hide all analysis
            </button>
          </div>
          {anomalyLayers.length > 0 ? (
            <ul className="map-analysis-layer-list">
              {anomalyLayers.map((layer) => {
                const checked = visibleAnalysisLayers.some(
                  (candidate) => candidate.layerId === layer.layerId,
                );
                return (
                  <li key={layer.layerId}>
                    <label>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(event) =>
                          setAnalysisLayerVisible(
                            layer.layerId,
                            event.currentTarget.checked,
                          )
                        }
                      />
                      <i className={layer.kind} aria-hidden="true" />
                      <span>{layer.label}</span>
                    </label>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="map-display-empty">No analysis layers are loaded.</p>
          )}
          <small>
            Display choices are private to this browser session. They do not
            alter laboratory results, evidence, review, or progression.
          </small>
        </section>

        <section className="map-display-section" aria-labelledby="facility-map-index-heading">
          <header>
            <div>
              <p className="eyebrow">Keyboard navigation</p>
              <h4 id="facility-map-index-heading">Facility sites</h4>
            </div>
            <small>Coordinate precision Â±25 km</small>
          </header>
          <div className="map-facility-index">
            {locations.map((location) => (
              <button
                key={location.id}
                type="button"
                aria-current={location.id === selectedId ? "location" : undefined}
                onClick={() => {
                  displayDialogRef.current?.close();
                  onSelect(location.id);
                }}
              >
                {location.shortName}
              </button>
            ))}
          </div>
        </section>

        <section className="map-display-section" aria-labelledby="reference-layer-heading">
          <header>
            <div>
              <p className="eyebrow">Public evidence context</p>
              <h4 id="reference-layer-heading">Reference overlays</h4>
            </div>
            <strong>
              {Object.values(externalSettings).filter((layer) => layer.visible).length} active
            </strong>
          </header>
          <div className="environmental-layer-list">
            {EXTERNAL_MAP_LAYERS.map((definition) => {
              const setting = externalSettings[definition.id];
              const dynamicalDataset = DYNAMICAL_DATASETS.find(
                (dataset) => dataset.id === definition.id,
              );
              const dynamicalRenderState = dynamicalDataset
                ? dynamicalRenderStates[dynamicalDataset.id]
                : null;
              return (
                <section
                  key={definition.id}
                  className={setting.visible ? "environmental-layer active" : "environmental-layer"}
                >
                  <label>
                    <input
                      type="checkbox"
                      checked={setting.visible}
                      onChange={(event) => updateExternalLayer(
                        definition.id,
                        { visible: event.currentTarget.checked },
                      )}
                    />
                    <span>
                      <strong>{definition.label}</strong>
                      <small>{definition.provider}</small>
                    </span>
                  </label>
                  <p>{definition.description}</p>
                  {setting.visible ? (
                    <label className="environmental-layer-opacity">
                      <span>Opacity</span>
                      <input
                        type="range"
                        min="0.1"
                        max="1"
                        step="0.05"
                        value={setting.opacity}
                        onChange={(event) => updateExternalLayer(
                          definition.id,
                          { opacity: Number(event.currentTarget.value) },
                        )}
                      />
                      <output>{Math.round(setting.opacity * 100)}%</output>
                    </label>
                  ) : null}
                  {definition.id === "nasa-true-color" && setting.visible ? (
                    <small className="environmental-layer-state">Observed {satelliteDate} UTC</small>
                  ) : null}
                  {definition.id === "noaa-radar" && setting.visible ? (
                    <small className="environmental-layer-state">Latest composite Â· ~5 min cadence</small>
                  ) : null}
                  {definition.id === "nws-alerts" && setting.visible ? (
                    <div className="environmental-layer-alert-state">
                      <small>{alertStatus} Â· {alertCount} polygon{alertCount === 1 ? "" : "s"}</small>
                      <button
                        type="button"
                        onClick={() => setAlertRefresh((revision) => revision + 1)}
                      >
                        Refresh
                      </button>
                    </div>
                  ) : null}
                  {definition.id === "uap-public-reports" && setting.visible ? (
                    <div className="public-report-timeline">
                      <div>
                        <strong>{reportEndYear - reportWindowYears + 1} - {reportEndYear}</strong>
                        <small>
                          {visibleReportCount.toLocaleString()} visible ·{" "}
                          {publicReports.length.toLocaleString()} loaded ·{" "}
                          {reportStatus}
                        </small>
                      </div>
                      <input
                        type="range"
                        min={reportYearExtent[0]}
                        max={reportYearExtent[1]}
                        step="1"
                        value={reportEndYear}
                        aria-label="Public report timeline end year"
                        onChange={(event) =>
                          setReportEndYear(Number(event.currentTarget.value))
                        }
                      />
                      <div className="public-report-filter-grid">
                        <label>
                          Window
                          <select
                            value={reportWindowYears}
                            onChange={(event) =>
                              setReportWindowYears(Number(event.currentTarget.value))
                            }
                          >
                            <option value="1">1 year</option>
                            <option value="5">5 years</option>
                            <option value="10">10 years</option>
                            <option value="25">25 years</option>
                          </select>
                        </label>
                        <label>
                          Source
                          <select
                            value={reportSourceFilter}
                            onChange={(event) =>
                              setReportSourceFilter(event.currentTarget.value)
                            }
                          >
                            <option value="all">Historical + UFOSINT</option>
                            <option value="ufosint">UFOSINT only</option>
                            <option value="historical">Historical only</option>
                          </select>
                        </label>
                        <label>
                          Quality
                          <select
                            value={reportMinimumQuality}
                            onChange={(event) =>
                              setReportMinimumQuality(Number(event.currentTarget.value))
                            }
                            disabled={reportSourceFilter === "historical"}
                          >
                            <option value="51">51+</option>
                            <option value="60">60+</option>
                            <option value="70">70+</option>
                            <option value="80">80+</option>
                            <option value="90">90+</option>
                          </select>
                        </label>
                        <label className="public-report-search">
                          Search
                          <input
                            type="search"
                            value={reportSearch}
                            placeholder="Place, shape, source, summary"
                            onChange={(event) =>
                              setReportSearch(event.currentTarget.value)
                            }
                          />
                        </label>
                      </div>
                      <label className="public-report-toggle">
                        <input
                          type="checkbox"
                          checked={reportCurrentOnly}
                          onChange={(event) =>
                            setReportCurrentOnly(event.currentTarget.checked)
                          }
                        />
                        UFOSINT current-index records only
                      </label>
                      <button
                        type="button"
                        className="public-report-reset"
                        onClick={() => {
                          setReportSourceFilter("all");
                          setReportSearch("");
                          setReportMinimumQuality(51);
                          setReportCurrentOnly(false);
                          setReportWindowYears(5);
                          setReportEndYear(reportYearExtent[1]);
                        }}
                      >
                        Reset report filters
                      </button>
                      <section
                        className="public-report-sidequest-index"
                        aria-labelledby="public-report-sidequest-index-heading"
                      >
                        <h5 id="public-report-sidequest-index-heading">
                          {readOnly ? "Public report records" : "Keyboard-accessible sidequests"}
                        </h5>
                        {keyboardSidequestReports.length > 0 ? (
                          <>
                            <p>
                              {readOnly
                                ? "Showing up to 25 eligible UFOSINT reports that match the current filters. Sidequest participation opens with sign-in."
                                : "Showing up to 25 eligible UFOSINT reports that match the current filters."}
                            </p>
                            <ul>
                              {keyboardSidequestReports.map((report) => (
                                <li key={report.reportId}>
                                  {readOnly ? (
                                    <span>{report.title} — {report.locationName} ({report.observedYear})</span>
                                  ) : (
                                    <button
                                      type="button"
                                      className="public-report-sidequest-launch"
                                      onClick={() => {
                                        displayDialogRef.current?.close();
                                        _onSidequestReportIdChange(report.reportId);
                                      }}
                                    >
                                      Investigate {report.title} — {report.locationName} (
                                      {report.observedYear})
                                    </button>
                                  )}
                                </li>
                              ))}
                            </ul>
                          </>
                        ) : (
                          <p>No eligible UFOSINT reports match the current filters.</p>
                        )}
                      </section>
                      <nav aria-label="Public reporting destinations">
                        <a
                          href="https://www.uapdrop.com/data.html"
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          Historical dataset
                        </a>
                        <a
                          href="https://nuforc.org/file-a-report/"
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          File a report
                        </a>
                      </nav>
                    </div>
                  ) : null}
                  {dynamicalDataset && setting.visible ? (
                    <div className="dynamical-layer-state">
                      <strong className={`dynamical-render-status ${dynamicalRenderState?.phase ?? "idle"}`}>
                        Render: {dynamicalRenderState?.phase ?? "idle"}
                      </strong>
                      <small>{dynamicalRenderState?.detail}</small>
                      {dynamicalRenderState?.phase === "ready" ? (
                        <small>
                          {dynamicalRenderState.variable} ({dynamicalRenderState.units}) · valid {new Date(
                            dynamicalRenderState.validTime ?? "",
                          ).toLocaleString()} · {dynamicalRenderState.kind}
                        </small>
                      ) : null}
                      {dynamicalRenderState?.attribution ? (
                        <small>{dynamicalRenderState.attribution}</small>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => setDynamicalRenderRefresh((revision) => revision + 1)}
                        disabled={dynamicalRenderState?.phase === "loading"}
                      >
                        Refresh viewport render
                      </button>
                      <strong>
                        {dynamicalContextCounts[dynamicalDataset.id].toLocaleString()} query-compatible
                        report window{dynamicalContextCounts[dynamicalDataset.id] === 1 ? "" : "s"}
                      </strong>
                      <small>
                        {dynamicalDataset.role.replaceAll("-", " ")} · {dynamicalDataset.license}
                        {dynamicalDataset.experimental ? " · experimental" : ""}
                      </small>
                      <small>
                        {reportStatus}. Markers show catalog overlap, not retrieved weather values.
                      </small>
                      <small>{dynamicalDataset.limitation}</small>
                      <a
                        href={dynamicalDataset.sourceUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        Dataset record
                      </a>
                    </div>
                  ) : null}
                </section>
              );
            })}
          </div>
          <small>Reference overlays have no progression effect.</small>
        </section>

        <form method="dialog" className="map-display-dialog-footer">
          <button type="submit">Return to map</button>
        </form>
      </dialog>
      {sidequestReportId ? (
        <UfosintSidequestPanel
          key={sidequestReportId}
          reportId={sidequestReportId}
          report={selectedSidequestReport}
          sessionToken={_sessionToken}
          participant={_participant}
          presentation="drawer"
          onClose={() => _onSidequestReportIdChange(null)}
        />
      ) : null}
      {invalidSidequestReportId ? (
        <p className="geographic-field-map-error" role="alert">
          The sidequest report ID in this link is invalid.
        </p>
      ) : null}
      {mapError ? <p className="geographic-field-map-error">{mapError}</p> : null}
    </div>
  );
}
