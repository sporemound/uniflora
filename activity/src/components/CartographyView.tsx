import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { activityHref, type ActivityRoute } from "../lib/routes";
import type { PublicAnomalyMapLayer } from "../shared/geospatial";
import type { PublicLocation } from "../shared/public-state";
import type { UfosintActor } from "../shared/ufosint-sidequest";

const GeographicFieldMap = lazy(async () => {
  const module = await import("./GeographicFieldMap");
  return { default: module.GeographicFieldMap };
});

interface CartographyViewProps {
  route: ActivityRoute;
  locations: PublicLocation[];
  anomalyLayers: readonly PublicAnomalyMapLayer[];
  sessionToken: string | null;
  participant: UfosintActor | null;
  previewOnly?: boolean;
}

export function CartographyView({
  route,
  locations,
  anomalyLayers,
  sessionToken,
  participant,
  previewOnly = false,
}: CartographyViewProps) {
  const [selectedId, setSelectedId] = useState(
    locations.find((location) => location.status === "focus")?.id ??
      locations[0]?.id ??
      "",
  );

  useEffect(() => {
    if (locations.some((location) => location.id === selectedId)) {
      return;
    }
    setSelectedId(
      locations.find((location) => location.status === "focus")?.id ??
        locations[0]?.id ??
        "",
    );
  }, [locations, selectedId]);

  const setSidequestReportId = useCallback((reportId: string | null) => {
    const current = new URL(window.location.href);
    if (reportId) {
      current.searchParams.set("sidequest", reportId);
    } else {
      current.searchParams.delete("sidequest");
    }
    window.history.replaceState(
      null,
      "",
      `${current.pathname}${current.search}${current.hash}`,
    );
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, []);

  return (
    <section
      className="cartography-view"
      id="cartography-content"
      tabIndex={-1}
      aria-labelledby="cartography-heading"
    >
      <header className="cartography-view-header">
        <div>
          <p className="eyebrow">Persistent institutional network</p>
          <h2 id="cartography-heading">Network cartography</h2>
          <p>
            Explore facility sites, laboratory output, weather, imagery, and
            public report history in one uninterrupted geographic field.
          </p>
        </div>
        <a href={activityHref("/#overview", route)}>Return to workspace</a>
      </header>

      <div className="cartography-view-map">
        <Suspense
          fallback={
            <div className="geographic-field-map-loading">
              Loading network cartography…
            </div>
          }
        >
          <GeographicFieldMap
            locations={locations}
            anomalyLayers={anomalyLayers}
            selectedId={selectedId}
            onSelect={setSelectedId}
            sessionToken={sessionToken}
            participant={participant}
            readOnly={previewOnly}
            initialSidequestReportId={
              new URLSearchParams(route.search).get("sidequest")
            }
            onSidequestReportIdChange={setSidequestReportId}
          />
        </Suspense>
      </div>
    </section>
  );
}
