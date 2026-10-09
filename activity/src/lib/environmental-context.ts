import {
  normalizeEnvironmentalContext,
  type EnvironmentalContextSnapshot,
  type EnvironmentalFacilityId,
} from "../shared/environmental-context";
import { siteAuthHeaders } from "./site-auth";

export async function loadEnvironmentalContext(
  facilityId: EnvironmentalFacilityId,
  sessionToken: string,
): Promise<EnvironmentalContextSnapshot> {
  const url = new URL("/api/environmental-context", window.location.origin);
  url.searchParams.set("facility", facilityId);
  const response = await fetch(url, {
    headers: {
      Accept: "application/json",
      ...siteAuthHeaders(sessionToken),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    const value = (await response.json().catch(() => null)) as {
      detail?: unknown;
    } | null;
    throw new Error(
      typeof value?.detail === "string"
        ? value.detail
        : `Environmental endpoint returned ${response.status}.`,
    );
  }
  const snapshot = normalizeEnvironmentalContext(await response.json());
  if (!snapshot || snapshot.facilityId !== facilityId) {
    throw new Error("Environmental payload failed validation.");
  }
  return snapshot;
}
