import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import type { PublicLocation } from "../shared/public-state";
import type { PublicAnomalyMapLayer } from "../shared/geospatial";

const GeographicFieldMap = lazy(async () => {
  const module = await import("./GeographicFieldMap");
  return { default: module.GeographicFieldMap };
});

interface InstitutionNetworkProps {
  locations: PublicLocation[];
  anomalyLayers?: readonly PublicAnomalyMapLayer[];
  cartographyHref?: string;
  previewOnly?: boolean;
  archived?: boolean;
}

type GalleryView = "geography" | "topology" | "access" | "clocks";

interface MapCoordinate {
  latitude: number;
  longitude: number;
  label: string;
  precisionKm: number;
  basis: "WGS84 facility site";
}

const nodePositions: Record<string, { x: number; y: number }> = {
  "interfacility-intake": { x: 90, y: 155 },
  "boundary-array": { x: 240, y: 72 },
  "aeronautical-incident-center": { x: 420, y: 68 },
  "aerial-phenomena-archive": { x: 570, y: 155 },
  "holography-laboratory": { x: 475, y: 270 },
  "subsurface-resonance-station": { x: 286, y: 292 },
  "quantum-state-institute": { x: 118, y: 258 },
};

const VIEW_LABELS: Record<GalleryView, { label: string; index: string }> = {
  geography: { label: "Geographic field", index: "01" },
  topology: { label: "Relay topology", index: "02" },
  access: { label: "Access field", index: "03" },
  clocks: { label: "Clock array", index: "04" },
};

// Compatibility for previously published 2.x snapshots. New v2 projections
// carry these coordinates directly from the current canonical content pack.
const LEGACY_MAP_COORDINATES: Record<string, MapCoordinate> = {
  boundary_array: {
    latitude: 40.88, longitude: -119.05, label: "Black Rock Sector, Nevada",
    precisionKm: 25, basis: "WGS84 facility site",
  },
  aeronautical_incident_center: {
    latitude: 38.73, longitude: -80.21, label: "Allegheny Sector, West Virginia",
    precisionKm: 25, basis: "WGS84 facility site",
  },
  aerial_phenomena_archive: {
    latitude: 43.25, longitude: -90.88, label: "Driftless Sector, Wisconsin",
    precisionKm: 25, basis: "WGS84 facility site",
  },
  holography_laboratory: {
    latitude: 37.73, longitude: -105.91, label: "San Luis Sector, Colorado",
    precisionKm: 25, basis: "WGS84 facility site",
  },
  subsurface_resonance_station: {
    latitude: 47.45, longitude: -123.53, label: "Cascadia Sector, Washington",
    precisionKm: 25, basis: "WGS84 facility site",
  },
  quantum_state_institute: {
    latitude: 44.12, longitude: -74.31, label: "Adirondack Sector, New York",
    precisionKm: 25, basis: "WGS84 facility site",
  },
};

const CONUS_OUTLINE: ReadonlyArray<readonly [number, number]> = [
  [-124.7, 48.4], [-123.0, 42.0], [-124.2, 40.0], [-121.0, 34.0],
  [-117.1, 32.5], [-111.0, 31.3], [-106.5, 31.8], [-103.0, 29.8],
  [-97.0, 25.9], [-91.0, 29.0], [-88.0, 30.3], [-82.0, 25.2],
  [-80.0, 32.0], [-75.0, 35.0], [-69.8, 43.0], [-71.0, 45.0],
  [-79.0, 43.0], [-83.0, 46.0], [-89.0, 48.0], [-95.0, 49.0],
  [-110.0, 49.0], [-124.7, 48.4],
];

function canonicalLocationId(locationId: string): string {
  return locationId.replaceAll("_", "-");
}

function nodePosition(locationId: string): { x: number; y: number } | undefined {
  return nodePositions[locationId] ?? nodePositions[canonicalLocationId(locationId)];
}

function mapCoordinate(location: PublicLocation): MapCoordinate | null {
  return location.mapCoordinates ??
    LEGACY_MAP_COORDINATES[location.id] ??
    LEGACY_MAP_COORDINATES[location.id.replaceAll("-", "_")] ??
    null;
}

function projectMap(latitude: number, longitude: number): { x: number; y: number } {
  return {
    x: 40 + ((longitude + 125) / 59) * 580,
    y: 25 + ((50 - latitude) / 26) * 285,
  };
}

function statusLabel(status: PublicLocation["status"]): string {
  switch (status) {
    case "focus":
      return "current focus";
    case "available":
      return "available";
    case "locked":
      return "not yet available";
  }
}

function facilityTime(location: PublicLocation, now: Date): string {
  try {
    return new Intl.DateTimeFormat("en-US", {
      timeZone: location.timezone,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(now);
  } catch {
    return "--:--:--";
  }
}

function timezoneLabel(location: PublicLocation, now: Date): string {
  try {
    return new Intl.DateTimeFormat("en-US", {
      timeZone: location.timezone,
      timeZoneName: "short",
    })
      .formatToParts(now)
      .find((part) => part.type === "timeZoneName")?.value ?? location.timezone;
  } catch {
    return location.timezone;
  }
}

export function InstitutionNetwork({
  locations,
  anomalyLayers = [],
  cartographyHref,
  previewOnly = false,
  archived = false,
}: InstitutionNetworkProps) {
  const [view, setView] = useState<GalleryView>("geography");
  const [selectedId, setSelectedId] = useState<string>(
    locations.find((location) => location.status === "focus")?.id ??
      locations[0]?.id ??
      "",
  );
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!locations.some((location) => location.id === selectedId)) {
      setSelectedId(
        locations.find((location) => location.status === "focus")?.id ??
          locations[0]?.id ??
          "",
      );
    }
  }, [locations, selectedId]);

  const selected =
    locations.find((location) => location.id === selectedId) ??
    locations[0] ??
    null;
  const path = useMemo(
    () =>
      locations
        .map((location) => nodePosition(location.id))
        .filter((position): position is { x: number; y: number } => Boolean(position)),
    [locations],
  );
  const activeTotal = locations.reduce(
    (total, location) => total + location.activeAssignments,
    0,
  );
  const availableTotal = locations.filter(
    (location) => location.status !== "locked",
  ).length;
  const maximumAssignments = Math.max(
    1,
    ...locations.map((location) => location.activeAssignments),
  );

  return (
    <section className="network-panel network-gallery" aria-labelledby="network-heading">
      <div className="network-gallery-heading">
        <div>
          <p className="eyebrow">{archived ? "Captured institutional visualization bank" : "Live institutional visualization bank"}</p>
          <h2 id="network-heading">Network cartography</h2>
          <p>
            Four renderings of the signed room projection. Diagram positions are
            operational topology, not geographic coordinates.
          </p>
        </div>
        <div className="network-gallery-readout" aria-label="Network summary">
          <strong>{String(availableTotal).padStart(2, "0")}/{String(locations.length).padStart(2, "0")}</strong>
          <span>facilities open</span>
          <small>{activeTotal} active assignments</small>
          {cartographyHref ? (
            <a href={cartographyHref}>Open full-page map</a>
          ) : null}
        </div>
      </div>

      <div className="network-gallery-tabs" role="tablist" aria-label="Network renderings">
        {(Object.keys(VIEW_LABELS) as GalleryView[]).map((galleryView) => (
          <button
            key={galleryView}
            type="button"
            role="tab"
            aria-selected={view === galleryView}
            aria-controls={`network-view-${galleryView}`}
            className={view === galleryView ? "active" : ""}
            onClick={() => setView(galleryView)}
          >
            <span>{VIEW_LABELS[galleryView].index}</span>
            {VIEW_LABELS[galleryView].label}
          </button>
        ))}
      </div>

      <div
        className={`network-gallery-stage network-gallery-stage--${view}`}
        id={`network-view-${view}`}
        role="tabpanel"
      >
        {view === "geography" ? (
          <Suspense fallback={<div className="geographic-field-map-loading">Loading geographic field…</div>}>
            <GeographicFieldMap
              locations={locations}
              anomalyLayers={anomalyLayers}
              selectedId={selected?.id ?? ""}
              onSelect={setSelectedId}
              readOnly={previewOnly}
              onSidequestReportIdChange={(reportId) => {
                if (!reportId) return;
                const destination = new URL(window.location.href);
                destination.pathname = "/cartography";
                destination.searchParams.set("sidequest", reportId);
                window.history.pushState(
                  null,
                  "",
                  `${destination.pathname}${destination.search}${destination.hash}`,
                );
                window.dispatchEvent(new PopStateEvent("popstate"));
              }}
            />
          </Suspense>
        ) : null}

        {false ? (
          <svg
            className="network-map"
            viewBox="0 0 660 360"
            role="img"
            aria-labelledby="geographic-map-title geographic-map-description"
          >
            <title id="geographic-map-title">Facility geography</title>
            <desc id="geographic-map-description">
              A continental map showing the six facility sectors in Nevada,
              West Virginia, Wisconsin, Colorado, California, and New York.
            </desc>
            <defs>
              <radialGradient id="coverage-field">
                <stop offset="0" stopColor="#72bcc8" stopOpacity="0.33" />
                <stop offset="0.35" stopColor="#72bcc8" stopOpacity="0.12" />
                <stop offset="1" stopColor="#72bcc8" stopOpacity="0" />
              </radialGradient>
              <pattern id="map-grid" width="58" height="55" patternUnits="userSpaceOnUse">
                <path d="M 58 0 L 0 0 0 55" className="network-grid-line" />
              </pattern>
            </defs>
            <rect width="660" height="360" className="network-field" />
            <rect width="660" height="360" fill="url(#map-grid)" />
            <path
              d={`M ${CONUS_OUTLINE.map(([longitude, latitude]) => {
                const point = projectMap(latitude, longitude);
                return `${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
              }).join(" L ")} Z`}
              className="network-map-land"
            />
            {[30, 40, 50].map((latitude) => {
              const { y } = projectMap(latitude, -125);
              return (
                <g key={latitude}>
                  <line x1="40" x2="620" y1={y} y2={y} className="network-map-graticule" />
                  <text x="13" y={y + 3} className="network-coordinate-label">{latitude}°N</text>
                </g>
              );
            })}
            {[-120, -100, -80].map((longitude) => {
              const { x } = projectMap(24, longitude);
              return (
                <g key={longitude}>
                  <line x1={x} x2={x} y1="25" y2="310" className="network-map-graticule" />
                  <text x={x} y="333" textAnchor="middle" className="network-coordinate-label">{Math.abs(longitude)}°W</text>
                </g>
              );
            })}
            <text x="18" y="18" className="network-coordinate-label">WGS84 / FACILITY SITES / ±25 KM</text>
            {anomalyLayers
              .filter((layer) => layer.kind === "heatmap")
              .flatMap((layer) =>
                layer.cells.map((cell) => {
                  const point = projectMap(cell.latitude, cell.longitude);
                  return (
                    <circle
                      key={`${layer.layerId}-${cell.cellId}`}
                      cx={point.x}
                      cy={point.y}
                      r={Math.max(7, cell.radiusKm * 0.11)}
                      className="network-anomaly-heat"
                      style={{ opacity: Math.min(0.72, Math.max(0.08, cell.intensity)) }}
                    >
                      <title>{`${layer.label}: intensity ${cell.intensity.toFixed(2)}; ${cell.sourceReferences.length} source references`}</title>
                    </circle>
                  );
                }),
              )}
            {anomalyLayers
              .filter((layer) => layer.kind === "trajectory")
              .map((layer) => (
                <path
                  key={layer.layerId}
                  d={layer.samples
                    .map((sample, index) => {
                      const point = projectMap(sample.latitude, sample.longitude);
                      return `${index === 0 ? "M" : "L"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
                    })
                    .join(" ")}
                  className="network-anomaly-trajectory"
                >
                  <title>{`${layer.label}: ${layer.samples.length} ordered observations`}</title>
                </path>
              ))}
            <text x="642" y="350" textAnchor="end" className="network-coordinate-label">
              {anomalyLayers.length > 0
                ? `ANALYSIS LAYERS: ${anomalyLayers.length} LOADED`
                : "ANALYSIS LAYERS: READY / NONE LOADED"}
            </text>
            {locations.map((location, index) => {
              const coordinate = mapCoordinate(location);
              if (!coordinate) return null;
              const point = projectMap(coordinate.latitude, coordinate.longitude);
              const isSelected = location.id === selected?.id;
              const labelOnLeft = false;
              return (
                <g
                  key={location.id}
                  className={`network-map-site ${location.status}${isSelected ? " selected" : ""}`}
                  transform={`translate(${point.x} ${point.y})`}
                  role="button"
                  tabIndex={0}
                  aria-label={`${location.name}, ${coordinate.label}; ${statusLabel(location.status)}`}
                  onClick={() => setSelectedId(location.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelectedId(location.id);
                    }
                  }}
                >
                  <circle r="48" className="network-map-coverage" />
                  <circle r={location.status === "focus" ? 8 : 6} className="network-map-point" />
                  <text
                    x={labelOnLeft ? -11 : 11}
                    y="-7"
                    textAnchor={labelOnLeft ? "end" : "start"}
                    className="network-map-index"
                  >
                    {String(index + 1).padStart(2, "0")}
                  </text>
                  <text
                    x={labelOnLeft ? -11 : 11}
                    y="7"
                    textAnchor={labelOnLeft ? "end" : "start"}
                    className="network-map-label"
                  >
                    {location.shortName}
                  </text>
                </g>
              );
            })}
          </svg>
        ) : null}

        {view === "topology" ? (
          <svg
            className="network-svg"
            viewBox="0 0 660 360"
            role="img"
            aria-labelledby="network-title network-description"
          >
            <title id="network-title">The Missing Interior {archived ? "captured" : "live"} institutional topology</title>
            <desc id="network-description">
              A selectable schematic of six institutions showing current focus,
              availability, locked access, and active assignment counts.
            </desc>
            <defs>
              <pattern id="network-grid" width="30" height="30" patternUnits="userSpaceOnUse">
                <path d="M 30 0 L 0 0 0 30" className="network-grid-line" />
              </pattern>
              <filter id="network-glow" x="-80%" y="-80%" width="260%" height="260%">
                <feGaussianBlur stdDeviation="5" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
            </defs>
            <rect width="660" height="360" className="network-field" />
            <rect width="660" height="360" fill="url(#network-grid)" />
            <circle cx="330" cy="180" r="145" className="network-orbit" />
            <circle cx="330" cy="180" r="92" className="network-orbit secondary" />
            <path
              className="network-route network-route-glow"
              d={path.length > 1 ? `M ${path.map(({ x, y }) => `${x} ${y}`).join(" L ")}` : ""}
            />
            <path
              className="network-route"
              d={path.length > 1 ? `M ${path.map(({ x, y }) => `${x} ${y}`).join(" L ")}` : ""}
            />
            <text x="18" y="28" className="network-coordinate-label">NORMALIZED RELAY FRAME / {archived ? "ARCHIVE" : "LIVE"}</text>
            <text x="642" y="340" textAnchor="end" className="network-coordinate-label">NON-GEOGRAPHIC</text>

            {locations.map((location, index) => {
              const position = nodePosition(location.id);
              if (!position) return null;
              const isSelected = location.id === selected?.id;
              return (
                <g
                  className={`network-node ${location.status}${isSelected ? " selected" : ""}`}
                  key={location.id}
                  transform={`translate(${position.x} ${position.y})`}
                  role="button"
                  tabIndex={0}
                  aria-label={`${location.name}: ${statusLabel(location.status)}; ${location.activeAssignments} active assignments`}
                  onClick={() => setSelectedId(location.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelectedId(location.id);
                    }
                  }}
                >
                  {location.status === "focus" ? <circle r="39" className="node-pulse" /> : null}
                  <circle r={location.status === "focus" ? 29 : 24} className="node-core" />
                  <text className="node-index" textAnchor="middle" y="-38">
                    {String(index + 1).padStart(2, "0")}
                  </text>
                  <text className="node-count" textAnchor="middle" y="5">
                    {location.activeAssignments}
                  </text>
                  <text className="node-label" textAnchor="middle" y="47">
                    {location.shortName}
                  </text>
                </g>
              );
            })}
          </svg>
        ) : null}

        {view === "access" ? (
          <div className="network-access-map" aria-label="Facility access and occupancy map">
            <div className="network-access-axis" aria-hidden="true">
              <span>SEALED</span><i /><span>ACTIVE</span>
            </div>
            {locations.map((location, index) => (
              <button
                type="button"
                className={`network-access-lane ${location.status}${location.id === selected?.id ? " selected" : ""}`}
                key={location.id}
                onClick={() => setSelectedId(location.id)}
              >
                <span className="network-access-index">{String(index + 1).padStart(2, "0")}</span>
                <span className="network-access-name">
                  <strong>{location.shortName}</strong>
                  <small>{statusLabel(location.status)}</small>
                </span>
                <span className="network-access-track" aria-hidden="true">
                  <i style={{ width: `${Math.max(4, (location.activeAssignments / maximumAssignments) * 100)}%` }} />
                </span>
                <span className="network-access-count">{location.activeAssignments}</span>
              </button>
            ))}
          </div>
        ) : null}

        {view === "clocks" ? (
          <div className="network-clock-array" aria-label="Live facility clock array">
            {locations.map((location, index) => (
              <button
                type="button"
                className={`network-clock ${location.status}${location.id === selected?.id ? " selected" : ""}`}
                key={location.id}
                onClick={() => setSelectedId(location.id)}
              >
                <span>{String(index + 1).padStart(2, "0")} / {location.shortName}</span>
                <strong>{facilityTime(location, now)}</strong>
                <small>{timezoneLabel(location, now)} · {statusLabel(location.status)}</small>
                <i aria-hidden="true" />
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {selected ? (
        <footer className="network-inspector" aria-live="polite">
          <div className={`network-inspector-status ${selected.status}`}>
            <i aria-hidden="true" />
            <span>{statusLabel(selected.status)}</span>
          </div>
          <div>
            <span>Selected facility</span>
            <strong>{selected.name}</strong>
            <small>{mapCoordinate(selected)?.label}</small>
          </div>
          <div>
            <span>Local clock</span>
            <strong>{facilityTime(selected, now)} <small>{timezoneLabel(selected, now)}</small></strong>
          </div>
          <div>
            <span>Occupancy</span>
            <strong>{selected.activeAssignments} active</strong>
          </div>
        </footer>
      ) : null}
    </section>
  );
}
