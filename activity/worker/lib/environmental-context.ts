import {
  ENVIRONMENTAL_FACILITIES,
  isEnvironmentalFacilityId,
  type EnvironmentalContextSnapshot,
  type EnvironmentalReading,
  type EnvironmentalSourceStatus,
} from "../../src/shared/environmental-context";
import { HttpError } from "./errors";

type JsonRecord = Record<string, unknown>;

interface WeatherResult {
  readings: EnvironmentalReading[];
  source: EnvironmentalSourceStatus;
}

interface EarthquakeResult {
  readings: EnvironmentalReading[];
  source: EnvironmentalSourceStatus;
}

interface SpaceWeatherResult {
  readings: EnvironmentalReading[];
  source: EnvironmentalSourceStatus;
}

const SNAPSHOT_CACHE = new Map<
  string,
  { expiresAt: number; value: EnvironmentalContextSnapshot }
>();
const CACHE_MILLISECONDS = 2 * 60 * 1_000;
const REQUEST_TIMEOUT_MILLISECONDS = 5_500;
const MAX_UPSTREAM_BYTES = 384 * 1_024;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function text(value: unknown, maximum = 512): string {
  return typeof value === "string" ? value.slice(0, maximum) : "";
}

function clamp(value: number): number {
  return Math.min(1, Math.max(0, value));
}

async function fetchJson(url: string): Promise<unknown> {
  const response = await fetch(url, {
    headers: {
      Accept: "application/geo+json, application/json",
      "User-Agent":
        "Uniflora/0.4 (+https://example.invalid/uniflora)",
    },
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MILLISECONDS),
  });
  if (!response.ok) {
    throw new Error(`upstream returned ${response.status}`);
  }
  const declared = Number.parseInt(response.headers.get("Content-Length") ?? "0", 10);
  if (Number.isFinite(declared) && declared > MAX_UPSTREAM_BYTES) {
    throw new Error("upstream response exceeded the read budget");
  }
  const body = await response.text();
  if (new TextEncoder().encode(body).byteLength > MAX_UPSTREAM_BYTES) {
    throw new Error("upstream response exceeded the read budget");
  }
  return JSON.parse(body) as unknown;
}

function unavailableSource(
  id: EnvironmentalSourceStatus["id"],
  label: string,
  sourceUrl: string,
  error: unknown,
): EnvironmentalSourceStatus {
  return {
    id,
    label,
    status: "unavailable",
    observedAt: null,
    detail:
      error instanceof Error
        ? `No current reading: ${error.message.slice(0, 180)}.`
        : "No current reading.",
    sourceUrl,
  };
}

async function weather(
  latitude: number,
  longitude: number,
): Promise<WeatherResult> {
  const pointUrl = `https://api.weather.gov/points/${latitude.toFixed(4)},${longitude.toFixed(4)}`;
  try {
    const point = await fetchJson(pointUrl);
    if (!isRecord(point) || !isRecord(point.properties)) {
      throw new Error("point metadata was malformed");
    }
    const stationsUrl = text(point.properties.observationStations, 1_024);
    if (!stationsUrl.startsWith("https://api.weather.gov/")) {
      throw new Error("observation-station route was unavailable");
    }
    const stations = await fetchJson(`${stationsUrl}?limit=1`);
    if (!isRecord(stations) || !Array.isArray(stations.features)) {
      throw new Error("station list was malformed");
    }
    const first = stations.features[0];
    const stationId =
      isRecord(first) && isRecord(first.properties)
        ? text(first.properties.stationIdentifier, 32)
        : "";
    if (!/^[A-Z0-9]{3,8}$/u.test(stationId)) {
      throw new Error("nearest station identifier was unavailable");
    }
    const observationUrl =
      `https://api.weather.gov/stations/${encodeURIComponent(stationId)}/observations/latest`;
    const observation = await fetchJson(observationUrl);
    if (!isRecord(observation) || !isRecord(observation.properties)) {
      throw new Error("latest observation was malformed");
    }
    const properties = observation.properties;
    const measurement = (name: string): number | null => {
      const candidate = properties[name];
      return isRecord(candidate) ? finite(candidate.value) : null;
    };
    const temperature = measurement("temperature");
    const windMetersPerSecond = measurement("windSpeed");
    const visibilityMeters = measurement("visibility");
    const pressurePascals =
      measurement("barometricPressure") ?? measurement("seaLevelPressure");
    const observedAt = text(properties.timestamp, 64) || null;
    return {
      readings: [
        { id: "temperature", label: "Air temperature", value: temperature, unit: "°C", source: "nws" },
        {
          id: "wind",
          label: "Wind speed",
          value: windMetersPerSecond === null ? null : windMetersPerSecond * 3.6,
          unit: "km/h",
          source: "nws",
        },
        {
          id: "visibility",
          label: "Visibility",
          value: visibilityMeters === null ? null : visibilityMeters / 1_000,
          unit: "km",
          source: "nws",
        },
        {
          id: "pressure",
          label: "Air pressure",
          value: pressurePascals === null ? null : pressurePascals / 100,
          unit: "hPa",
          source: "nws",
        },
      ],
      source: {
        id: "nws",
        label: `NWS station ${stationId}`,
        status: "current",
        observedAt,
        detail: text(properties.textDescription, 180) || "Latest surface observation.",
        sourceUrl: observationUrl,
      },
    };
  } catch (error) {
    return {
      readings: [],
      source: unavailableSource("nws", "NWS surface observations", pointUrl, error),
    };
  }
}

async function earthquakes(
  latitude: number,
  longitude: number,
): Promise<EarthquakeResult> {
  const start = new Date(Date.now() - 24 * 60 * 60 * 1_000).toISOString();
  const url = new URL("https://earthquake.usgs.gov/fdsnws/event/1/query");
  url.search = new URLSearchParams({
    format: "geojson",
    latitude: latitude.toFixed(4),
    longitude: longitude.toFixed(4),
    maxradiuskm: "500",
    starttime: start,
    minmagnitude: "1",
    limit: "100",
    orderby: "time",
  }).toString();
  try {
    const collection = await fetchJson(url.toString());
    if (!isRecord(collection) || !Array.isArray(collection.features)) {
      throw new Error("event collection was malformed");
    }
    const magnitudes = collection.features.flatMap((feature) => {
      if (!isRecord(feature) || !isRecord(feature.properties)) return [];
      const magnitude = finite(feature.properties.mag);
      return magnitude === null ? [] : [magnitude];
    });
    const observedAt =
      isRecord(collection.metadata) && finite(collection.metadata.generated) !== null
        ? new Date(finite(collection.metadata.generated) as number).toISOString()
        : null;
    return {
      readings: [
        {
          id: "earthquakes",
          label: "Regional events · 24 h",
          value: collection.features.length,
          unit: "events",
          source: "usgs",
        },
        {
          id: "strongest-earthquake",
          label: "Strongest regional event",
          value: magnitudes.length > 0 ? Math.max(...magnitudes) : 0,
          unit: "magnitude",
          source: "usgs",
        },
      ],
      source: {
        id: "usgs",
        label: "USGS Earthquake Catalog",
        status: "current",
        observedAt,
        detail: "Events of magnitude 1+ within 500 km during the last 24 hours.",
        sourceUrl: url.toString(),
      },
    };
  } catch (error) {
    return {
      readings: [],
      source: unavailableSource("usgs", "USGS Earthquake Catalog", url.toString(), error),
    };
  }
}

function summaryValue(value: unknown, key: string): {
  value: number | null;
  observedAt: string | null;
} {
  if (!isRecord(value)) return { value: null, observedAt: null };
  const numeric = Number.parseFloat(String(value[key] ?? ""));
  return {
    value: Number.isFinite(numeric) ? numeric : null,
    observedAt: text(value.TimeStamp, 64) || null,
  };
}

async function spaceWeather(): Promise<SpaceWeatherResult> {
  const windUrl =
    "https://services.swpc.noaa.gov/products/summary/solar-wind-speed.json";
  const kpUrl =
    "https://services.swpc.noaa.gov/products/summary/planetary-k-index.json";
  try {
    const [windRaw, kpRaw] = await Promise.all([
      fetchJson(windUrl),
      fetchJson(kpUrl),
    ]);
    const wind = summaryValue(windRaw, "WindSpeed");
    const kp = summaryValue(kpRaw, "Kp");
    if (wind.value === null && kp.value === null) {
      throw new Error("summary values were unavailable");
    }
    return {
      readings: [
        {
          id: "solar-wind",
          label: "Solar-wind speed",
          value: wind.value,
          unit: "km/s",
          source: "swpc",
        },
        {
          id: "planetary-k",
          label: "Planetary K index",
          value: kp.value,
          unit: "Kp",
          source: "swpc",
        },
      ],
      source: {
        id: "swpc",
        label: "NOAA Space Weather Prediction Center",
        status: "current",
        observedAt: wind.observedAt ?? kp.observedAt,
        detail: "Current solar-wind speed and planetary magnetic activity.",
        sourceUrl: "https://services.swpc.noaa.gov/products/summary/",
      },
    };
  } catch (error) {
    return {
      readings: [],
      source: unavailableSource(
        "swpc",
        "NOAA Space Weather Prediction Center",
        "https://services.swpc.noaa.gov/products/summary/",
        error,
      ),
    };
  }
}

function reading(
  readings: readonly EnvironmentalReading[],
  id: EnvironmentalReading["id"],
): number | null {
  return readings.find((candidate) => candidate.id === id)?.value ?? null;
}

export async function environmentalContext(
  facilityId: string,
): Promise<EnvironmentalContextSnapshot> {
  if (!isEnvironmentalFacilityId(facilityId)) {
    throw new HttpError(400, "invalid_facility", "The environmental facility ID is not recognized.");
  }
  const cached = SNAPSHOT_CACHE.get(facilityId);
  if (cached && cached.expiresAt > Date.now()) return cached.value;

  const facility = ENVIRONMENTAL_FACILITIES[facilityId];
  const [weatherResult, earthquakeResult, spaceWeatherResult] = await Promise.all([
    weather(facility.latitude, facility.longitude),
    earthquakes(facility.latitude, facility.longitude),
    spaceWeather(),
  ]);
  const readings = [
    ...weatherResult.readings,
    ...earthquakeResult.readings,
    ...spaceWeatherResult.readings,
  ];
  const visibility = reading(readings, "visibility");
  const eventCount = reading(readings, "earthquakes");
  const strongest = reading(readings, "strongest-earthquake");
  const solarWind = reading(readings, "solar-wind");
  const kp = reading(readings, "planetary-k");

  const value: EnvironmentalContextSnapshot = {
    schemaVersion: "1.0.0",
    environment: "test",
    facilityId,
    facilityName: facility.name,
    facilityLabel: facility.label,
    latitude: facility.latitude,
    longitude: facility.longitude,
    retrievedAt: new Date().toISOString(),
    readings,
    indicators: [
      {
        id: "atmospheric-obscuration",
        label: "Atmospheric obscuration",
        value: visibility === null ? 0 : clamp(1 - visibility / 24),
        detail: "Display-only context derived from the nearest available visibility report.",
      },
      {
        id: "seismic-background",
        label: "Regional seismic activity",
        value:
          eventCount === null || strongest === null
            ? 0
            : clamp((eventCount / 20) * 0.45 + (strongest / 6) * 0.55),
        detail: "Display-only context derived from regional event count and magnitude.",
      },
      {
        id: "radio-propagation",
        label: "Radio propagation stress",
        value:
          solarWind === null || kp === null
            ? 0
            : clamp((solarWind / 1_000) * 0.35 + (kp / 9) * 0.65),
        detail: "Display-only context derived from solar-wind speed and planetary K.",
      },
    ],
    sources: [
      weatherResult.source,
      earthquakeResult.source,
      spaceWeatherResult.source,
    ],
  };
  SNAPSHOT_CACHE.set(facilityId, {
    expiresAt: Date.now() + CACHE_MILLISECONDS,
    value,
  });
  return value;
}
