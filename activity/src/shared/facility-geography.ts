import type { PublicLocation } from "./public-state";

export interface FacilityMapCoordinate {
  latitude: number;
  longitude: number;
  label: string;
  precisionKm: number;
  basis: "WGS84 facility site";
}

// Compatibility for previously published 2.x snapshots. New v2 projections
// carry these coordinates directly from the content pack.
const LEGACY_MAP_COORDINATES: Record<string, FacilityMapCoordinate> = {
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

export function facilityMapCoordinate(
  location: PublicLocation,
): FacilityMapCoordinate | null {
  return location.mapCoordinates ??
    LEGACY_MAP_COORDINATES[location.id] ??
    LEGACY_MAP_COORDINATES[location.id.replaceAll("-", "_")] ??
    null;
}
