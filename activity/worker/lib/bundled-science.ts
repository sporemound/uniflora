import type { RoomTicketRequest } from "../../src/shared/investigation-room";
import { HttpError } from "./errors";

const TIME_BASES = [
  "Zulu",
  "Facility local",
  "Source original",
  "Pacific",
  "Mountain",
  "Central",
  "Eastern",
] as const;

export interface BundledScientificScope {
  minimumSeconds: number;
  maximumSeconds: number;
  timeBases: string[];
}

export function bundledTestScientificScope(
  request: RoomTicketRequest,
): BundledScientificScope | null {
  if (
    request.environment !== "test" ||
    request.artifactId !== "artifact-phase3-sr03" ||
    request.visualizationId !== "viz_9c555925e5bc6da2fb0def5b"
  ) {
    return null;
  }

  const minimumSeconds = -4;
  const maximumSeconds = 11.99609375;
  if (
    request.minimumSeconds !== minimumSeconds ||
    request.maximumSeconds !== maximumSeconds ||
    request.timeBases.length !== TIME_BASES.length ||
    request.timeBases.some((basis, index) => basis !== TIME_BASES[index])
  ) {
    throw new HttpError(
      409,
      "room_visualization_scope_mismatch",
      "Room ticket bounds and time bases do not match the bundled scientific fixture.",
    );
  }

  return {
    minimumSeconds,
    maximumSeconds,
    timeBases: [...TIME_BASES],
  };
}
