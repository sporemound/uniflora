import type {
  PublicActivitySnapshot,
  PublicPosition,
} from "./public-state";

export const INVESTIGATION_ACCESS_IDENTITY = {
  packId: "missing_interior",
  contentVersion: "2.0.0-strategic-overhaul",
} as const;

export const CANONICAL_FACILITIES = [
  {
    id: "boundary_array",
    slug: "boundary-array",
    name: "Boundary Array",
    order: 1,
    positionId: "boundary_event",
  },
  {
    id: "aeronautical_incident_center",
    slug: "aeronautical-incident-center",
    name: "Aeronautical Incident Center",
    order: 2,
    positionId: "aeronautical_incident",
  },
  {
    id: "aerial_phenomena_archive",
    slug: "aerial-phenomena-archive",
    name: "Aerial Phenomena Archive",
    order: 3,
    positionId: "archive_convergence",
  },
  {
    id: "holography_laboratory",
    slug: "holography-laboratory",
    name: "Holography Laboratory",
    order: 4,
    positionId: "holographic_reconstruction",
  },
  {
    id: "subsurface_resonance_station",
    slug: "subsurface-resonance-station",
    name: "Subsurface Resonance Station",
    order: 5,
    positionId: "subsurface_resonance",
  },
  {
    id: "quantum_state_institute",
    slug: "quantum-state-institute",
    name: "Quantum State Institute",
    order: 6,
    positionId: "quantum_state",
  },
] as const;

export const CANONICAL_POSITIONS = [
  {
    id: "network_orientation",
    slug: "network-orientation",
    ordinal: 0,
    title: "The Network Before the Event",
    focusFacilityId: "boundary_array",
    nextPositionId: "boundary_event",
  },
  {
    id: "boundary_event",
    slug: "boundary-event",
    ordinal: 1,
    title: "First Return",
    focusFacilityId: "boundary_array",
    nextPositionId: "aeronautical_incident",
  },
  {
    id: "aeronautical_incident",
    slug: "aeronautical-incident",
    ordinal: 2,
    title: "The Track That Will Not Close",
    focusFacilityId: "aeronautical_incident_center",
    nextPositionId: "archive_convergence",
  },
  {
    id: "archive_convergence",
    slug: "archive-convergence",
    ordinal: 3,
    title: "A Pattern Without a Common Cause",
    focusFacilityId: "aerial_phenomena_archive",
    nextPositionId: "holographic_reconstruction",
  },
  {
    id: "holographic_reconstruction",
    slug: "holographic-reconstruction",
    ordinal: 4,
    title: "The Volume Defined by Its Absence",
    focusFacilityId: "holography_laboratory",
    nextPositionId: "subsurface_resonance",
  },
  {
    id: "subsurface_resonance",
    slug: "subsurface-resonance",
    ordinal: 5,
    title: "A Mode Without a Source Point",
    focusFacilityId: "subsurface_resonance_station",
    nextPositionId: "quantum_state",
  },
  {
    id: "quantum_state",
    slug: "quantum-state",
    ordinal: 6,
    title: "The View From the Missing Interior",
    focusFacilityId: "quantum_state_institute",
    nextPositionId: null,
  },
] as const;

export type CanonicalFacility = (typeof CANONICAL_FACILITIES)[number];
export type CanonicalFacilityId = CanonicalFacility["id"];
export type CanonicalPosition = (typeof CANONICAL_POSITIONS)[number];
export type CanonicalPositionId = CanonicalPosition["id"];

export type PositionProgression =
  | "completed"
  | "available"
  | "locked"
  | "unpublished";
export type FacilityAvailability = "available" | "locked" | "unknown";
export type FacilityAccessMode = "read-only" | "none" | "unknown";
export type PositionConsoleMode =
  | "workspace"
  | "reference"
  | "locked"
  | "unpublished";

export interface PositionAccessDisplay {
  position: CanonicalPosition;
  progression: PositionProgression;
  isCurrent: boolean;
  consoleMode: PositionConsoleMode;
}

export interface FacilityAccessDisplay {
  facility: CanonicalFacility;
  position: CanonicalPosition;
  availability: FacilityAvailability;
  isFocus: boolean;
  accessMode: FacilityAccessMode;
  activeAssignments: number | null;
  publishedLocationId: string | null;
}

export interface InvestigationAccessDisplayModel {
  packId: typeof INVESTIGATION_ACCESS_IDENTITY.packId;
  contentVersion: typeof INVESTIGATION_ACCESS_IDENTITY.contentVersion;
  projection:
    | "canonical-position-projection"
    | "transitional-facility-projection"
    | "mock-preview";
  positions: readonly PositionAccessDisplay[];
  facilities: readonly FacilityAccessDisplay[];
  disclaimer: string;
}

function publishedPositions(
  snapshot: PublicActivitySnapshot,
): readonly PublicPosition[] | null {
  return snapshot.schemaVersion === "2.1.0" ||
    snapshot.schemaVersion === "2.2.0" ||
    snapshot.schemaVersion === "2.3.0" ||
    snapshot.schemaVersion === "2.4.0"
    ? snapshot.positions
    : null;
}

function facilityAliases(facility: CanonicalFacility): readonly string[] {
  return [facility.id, facility.slug];
}

function matchesFacilityId(
  facility: CanonicalFacility,
  candidate: string,
): boolean {
  return facilityAliases(facility).includes(candidate);
}

export function buildAccessDisplayModel(
  snapshot: PublicActivitySnapshot,
): InvestigationAccessDisplayModel {
  const isAuthoritativeProjection = snapshot.source === "hypha";
  const positionsProjection = isAuthoritativeProjection
    ? publishedPositions(snapshot)
    : null;

  const positions = CANONICAL_POSITIONS.map((position) => {
    const published = positionsProjection?.find(({ id }) => id === position.id);
    const isCurrent =
      Boolean(published) && snapshot.positionId === position.id;

    return {
      position,
      progression: published?.progression ?? "unpublished",
      isCurrent,
      consoleMode: published?.consoleMode ?? "unpublished",
    } satisfies PositionAccessDisplay;
  });

  const facilities = CANONICAL_FACILITIES.map((facility) => {
    const position = CANONICAL_POSITIONS.find(
      ({ id }) => id === facility.positionId,
    );
    if (!position) {
      throw new Error(`Facility ${facility.id} has no position.`);
    }

    if (!isAuthoritativeProjection) {
      return {
        facility,
        position,
        availability: "unknown",
        isFocus: false,
        accessMode: "unknown",
        activeAssignments: null,
        publishedLocationId: null,
      } satisfies FacilityAccessDisplay;
    }

    const location = snapshot.locations.find(({ id }) =>
      matchesFacilityId(facility, id),
    );
    if (!location) {
      return {
        facility,
        position,
        availability: "unknown",
        isFocus: false,
        accessMode: "unknown",
        activeAssignments: null,
        publishedLocationId: null,
      } satisfies FacilityAccessDisplay;
    }

    const availability =
      location.status === "locked" ? "locked" : "available";
    const isFocus =
      location.status === "focus" &&
      matchesFacilityId(facility, snapshot.focusLocationId);

    return {
      facility,
      position,
      availability,
      isFocus,
      accessMode: availability === "available" ? "read-only" : "none",
      activeAssignments: location.activeAssignments,
      publishedLocationId: location.id,
    } satisfies FacilityAccessDisplay;
  });

  if (!isAuthoritativeProjection) {
    return {
      ...INVESTIGATION_ACCESS_IDENTITY,
      projection: "mock-preview",
      positions,
      facilities,
      disclaimer:
        "Preview data is not authoritative. Facility access and position progression are unknown, so preview routes cannot be entered.",
    };
  }

  if (!positionsProjection) {
    return {
      ...INVESTIGATION_ACCESS_IDENTITY,
      projection: "transitional-facility-projection",
      positions,
      facilities,
      disclaimer:
        "This signed schema 2.0 projection publishes facility availability only. Position progression is unpublished; an unpublished position is not evidence that it is locked.",
    };
  }

  return {
    ...INVESTIGATION_ACCESS_IDENTITY,
    projection: "canonical-position-projection",
    positions,
    facilities,
    disclaimer:
      "This catalogue is a read-only public projection. It does not grant movement, role, completion, or unlock authority.",
  };
}
