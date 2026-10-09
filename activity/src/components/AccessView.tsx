import type { ReactNode } from "react";
import { activityHref, type ActivityRoute } from "../lib/routes";
import {
  buildAccessDisplayModel,
  type CanonicalFacilityId,
  type FacilityAccessDisplay,
  type InvestigationAccessDisplayModel,
  type PositionAccessDisplay,
} from "../shared/investigation-access";
import type { PublicActivitySnapshot } from "../shared/public-state";
import { FacilityScienceLab } from "./FacilityScienceLab";

interface AccessViewProps {
  route: ActivityRoute;
  snapshot: PublicActivitySnapshot;
  sessionToken: string | null;
  loading: boolean;
  warning: string | null;
  lastRefresh: string;
  onRefresh: () => void | Promise<void>;
  archived?: boolean;
}

const FACILITY_DISCIPLINES: Record<
  CanonicalFacilityId,
  { discipline: string; description: string }
> = {
  boundary_array: {
    discipline: "Waveform and spectrum",
    description:
      "Clock alignment, propagation testing, waveform comparison, and spectral inspection.",
  },
  aeronautical_incident_center: {
    discipline: "Track fusion",
    description:
      "Bearing geometry, track-family comparison, and fusion-dependency auditing.",
  },
  aerial_phenomena_archive: {
    discipline: "Recurrence network",
    description:
      "Recurrence sampling, accession dependency, and source-independence analysis.",
  },
  holography_laboratory: {
    discipline: "Projection volume",
    description:
      "Phase registration, projection withholding, and volume-sensitivity analysis.",
  },
  subsurface_resonance_station: {
    discipline: "Depth-frequency modes",
    description:
      "Depth-frequency modes, station sensitivity, and multiphysics coupling.",
  },
  quantum_state_institute: {
    discipline: "Basis and state manifold",
    description:
      "Measurement-basis comparison, uncertainty masks, and state estimation.",
  },
};

const POSITION_SUMMARIES: Record<string, string> = {
  network_orientation:
    "All six facility consoles, geographic layers, and the report timeline are available before the first record arrives.",
  boundary_event:
    "An immense luminous phenomenon is observed at the boundary.",
  aeronautical_incident:
    "No single physical trajectory satisfies the complete instrument record.",
  archive_convergence:
    "Historical cases resolve into a distributed sampling pattern.",
  holographic_reconstruction:
    "The combined pattern reconstructs a volume defined by its absence.",
  subsurface_resonance:
    "The absent volume behaves as a regional physical mode.",
  quantum_state:
    "The full network temporarily forms a viewpoint from the missing interior.",
};

const BOUNDARY_SOLO_WORKFLOW = [
  {
    role: "Field Observer",
    task: "Examine the optical record, then inspect the optical record.",
  },
  {
    role: "Instrument Operator",
    task:
      "Examine the radio return, run the receiver diagnostic, then examine the unlocked diagnostic.",
  },
  {
    role: "Atmospheric Analyst",
    task: "Retrieve and examine the local weather record.",
  },
  {
    role: "Signal Correlator",
    task: "Compare optical and radio timing; retain the timing contradiction.",
  },
  {
    role: "Atmospheric Analyst",
    task: "Test atmospheric propagation against all three source classes.",
  },
  {
    role: "Protocol Auditor",
    task:
      "Document the upper-atmosphere collection gap, then draft the Position 1 assessment.",
  },
] as const;

function stateLabel(value: string): string {
  return value.replaceAll("-", " ");
}

function FacilitySchematic({
  facilityId,
}: {
  facilityId: CanonicalFacilityId;
}) {
  let drawing: ReactNode;

  switch (facilityId) {
    case "boundary_array":
      drawing = (
        <>
          <path d="M10 18 H170 M10 61 H170 M10 108 H170" opacity="0.25" />
          <path d="M10 40 C20 40 23 28 30 28 S40 53 48 53 S58 21 68 21 S79 51 89 51 S102 32 111 32 S123 44 133 44 S148 37 170 37" />
          <path d="M15 99 V82 M31 99 V75 M47 99 V88 M63 99 V69 M79 99 V79 M95 99 V91 M111 99 V84 M127 99 V93 M143 99 V89 M159 99 V96" />
          <path d="M10 99 H170" opacity="0.45" />
        </>
      );
      break;
    case "aeronautical_incident_center":
      drawing = (
        <>
          <path d="M10 96 L48 73 L77 49 L111 42 L169 12" />
          <path d="M10 96 L48 73 L80 65 L119 71 L169 102" strokeDasharray="5 5" />
          <path d="M10 96 L48 73 L70 34 L113 17 L169 24" opacity="0.46" />
          <circle cx="48" cy="73" r="5" fill="currentColor" />
          <path d="M15 108 H165 M15 108 V16" opacity="0.3" />
        </>
      );
      break;
    case "aerial_phenomena_archive":
      drawing = (
        <>
          <path d="M25 29 L71 18 L105 43 L153 22 M25 29 L49 67 L105 43 L131 82 L165 103 M49 67 L26 104 M49 67 L91 101 L131 82 M105 43 L165 53 L131 82" opacity="0.65" />
          <path d="M25 29 C62 46 88 63 131 82" strokeDasharray="4 4" />
          <circle cx="25" cy="29" r="6" fill="currentColor" />
          <circle cx="71" cy="18" r="3" fill="currentColor" />
          <circle cx="105" cy="43" r="7" fill="currentColor" />
          <circle cx="153" cy="22" r="4" fill="currentColor" />
          <circle cx="49" cy="67" r="5" fill="currentColor" />
          <circle cx="131" cy="82" r="6" fill="currentColor" />
          <circle cx="26" cy="104" r="3" fill="currentColor" />
          <circle cx="91" cy="101" r="4" fill="currentColor" />
          <circle cx="165" cy="103" r="3" fill="currentColor" />
          <circle cx="165" cy="53" r="4" fill="currentColor" />
        </>
      );
      break;
    case "holography_laboratory":
      drawing = (
        <>
          <path d="M48 29 L112 18 L153 49 L91 63 Z" />
          <path d="M48 29 V83 L91 108 V63 M91 108 L153 91 V49" />
          <path d="M68 48 L109 41 L132 58 L91 70 Z" strokeDasharray="4 4" />
          <path d="M68 48 V72 L91 86 V70 M91 86 L132 75 V58" strokeDasharray="4 4" />
          <path d="M10 19 L68 48 M170 25 L132 58 M18 110 L68 72" opacity="0.38" />
        </>
      );
      break;
    case "subsurface_resonance_station":
      drawing = (
        <>
          <path d="M9 25 H171 M9 53 H171 M9 81 H171 M9 109 H171" opacity="0.3" />
          <path d="M12 37 C28 13 43 61 60 37 S91 13 108 37 S140 61 168 37" />
          <path d="M12 68 C33 47 43 89 64 68 S95 47 116 68 S145 88 168 68" strokeDasharray="5 4" />
          <path d="M12 98 C39 84 54 112 80 98 S124 83 168 98" opacity="0.58" />
          <text x="14" y="15" fill="currentColor" stroke="none" fontSize="7">
            frequency
          </text>
          <text
            x="176"
            y="111"
            fill="currentColor"
            stroke="none"
            fontSize="7"
            textAnchor="end"
          >
            depth
          </text>
        </>
      );
      break;
    case "quantum_state_institute":
      drawing = (
        <>
          <ellipse cx="90" cy="60" rx="70" ry="25" />
          <ellipse cx="90" cy="60" rx="70" ry="25" transform="rotate(60 90 60)" />
          <ellipse cx="90" cy="60" rx="70" ry="25" transform="rotate(120 90 60)" />
          <circle cx="90" cy="60" r="7" fill="currentColor" />
          <circle cx="158" cy="54" r="4" fill="currentColor" />
          <circle cx="41" cy="12" r="4" fill="currentColor" />
          <circle cx="63" cy="113" r="4" fill="currentColor" />
        </>
      );
      break;
  }

  const facility = FACILITY_DISCIPLINES[facilityId];
  return (
    <figure className={`access-schematic access-schematic-${facilityId}`}>
      <svg
        viewBox="0 0 180 120"
        role="img"
        aria-labelledby={`${facilityId}-schematic-title ${facilityId}-schematic-description`}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <title id={`${facilityId}-schematic-title`}>
          {facility.discipline} instrument schematic
        </title>
        <desc id={`${facilityId}-schematic-description`}>
          An instrument-domain diagram identifying the analysis bench available
          in this facility console.
        </desc>
        {drawing}
      </svg>
      <figcaption>
        Instrument-domain index <span aria-hidden="true">·</span> interactive
        analysis below
      </figcaption>
    </figure>
  );
}

function AccessState({
  label,
  tone,
}: {
  label: string;
  tone: string;
}) {
  return (
    <span className={`access-state access-state-${tone}`}>
      <i aria-hidden="true" />
      {label}
    </span>
  );
}

function RefreshStatus({
  loading,
  warning,
  lastRefresh,
  onRefresh,
  authoritative,
  archived,
}: Pick<
  AccessViewProps,
  "loading" | "warning" | "lastRefresh" | "onRefresh"
> & { authoritative: boolean; archived: boolean }) {
  return (
    <aside className="access-refresh" aria-label="Published state status">
      <div>
        <strong>
          {loading
            ? "Refreshing public state"
            : archived
              ? "Captured signed archive"
            : authoritative
              ? "Signed state loaded"
              : "Preview state only"}
        </strong>
        <span>
          {lastRefresh === "not yet refreshed"
            ? lastRefresh
            : `Last checked ${lastRefresh}`}
        </span>
      </div>
      <button
        type="button"
        onClick={() => void onRefresh()}
        disabled={loading}
      >
        {loading ? "Refreshing…" : "Refresh state"}
      </button>
      {warning ? <p role="status">{warning}</p> : null}
    </aside>
  );
}

function AccessHeader({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children?: ReactNode;
}) {
  return (
    <header className="access-view-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {children}
    </header>
  );
}

function FacilityCard({
  item,
  route,
}: {
  item: FacilityAccessDisplay;
  route: ActivityRoute;
}) {
  const science = FACILITY_DISCIPLINES[item.facility.id];
  const state =
    item.accessMode === "read-only"
      ? { label: "Read-only access", tone: "available" }
      : item.availability === "locked"
        ? { label: "Locked", tone: "locked" }
        : { label: "Access unknown", tone: "unknown" };

  return (
    <li className={`access-card access-card-${state.tone}`}>
      <article>
        <div className="access-card-heading">
          <span className="access-index" aria-label={`Facility ${item.facility.order}`}>
            {String(item.facility.order).padStart(2, "0")}
          </span>
          <AccessState {...state} />
        </div>
        <FacilitySchematic facilityId={item.facility.id} />
        <p className="eyebrow">{science.discipline}</p>
        <h2>{item.facility.name}</h2>
        <p>{science.description}</p>
        <dl className="access-card-facts">
          <div>
            <dt>Position</dt>
            <dd>{item.position.title}</dd>
          </div>
          <div>
            <dt>Published assignments</dt>
            <dd>{item.activeAssignments ?? "Unpublished"}</dd>
          </div>
        </dl>
        <a href={activityHref(`/facilities/${item.facility.slug}`, route)}>
          {item.accessMode === "read-only"
            ? "Open read-only console"
            : "Inspect access state"}
          <span aria-hidden="true"> →</span>
        </a>
      </article>
    </li>
  );
}

function FacilitiesCatalogue({
  model,
  route,
  snapshot,
}: {
  model: InvestigationAccessDisplayModel;
  route: ActivityRoute;
  snapshot: PublicActivitySnapshot;
}) {
  const publishedFocus = snapshot.locations.find(
    ({ id }) => id === snapshot.focusLocationId,
  );
  const focusIsCanonical = model.facilities.some(
    ({ facility }) =>
      facility.id === snapshot.focusLocationId ||
      facility.slug === snapshot.focusLocationId,
  );

  return (
    <>
      <AccessHeader
        eyebrow="Institution network"
        title="Facility access consoles"
        description="All six facilities are visible here. A route exposes its console only when the signed state marks that facility available."
      >
        <div className="access-identity">
          <span>{model.packId}</span>
          <span>content {model.contentVersion}</span>
        </div>
      </AccessHeader>
      <p className="access-boundary-note" role="note">
        {model.disclaimer}
      </p>
      {snapshot.source === "hypha" && publishedFocus && !focusIsCanonical ? (
        <aside className="access-dispatch-hub" aria-labelledby="dispatch-hub-title">
          <div>
            <p className="eyebrow">Current public workspace · dispatch hub</p>
            <h2 id="dispatch-hub-title">{publishedFocus.name}</h2>
            <p>
              The published campaign currently focuses this transitional
              workspace. It is the shared intake/dispatch hub, not a seventh
              facility.
            </p>
          </div>
          <a href={activityHref("/", route)}>
            Open current workspace <span aria-hidden="true">→</span>
          </a>
        </aside>
      ) : null}
      <ol className="access-card-grid">
        {model.facilities.map((item) => (
          <FacilityCard key={item.facility.id} item={item} route={route} />
        ))}
      </ol>
    </>
  );
}

function FacilityDetail({
  item,
  model,
  route,
  snapshot,
  sessionToken,
}: {
  item: FacilityAccessDisplay;
  model: InvestigationAccessDisplayModel;
  route: ActivityRoute;
  snapshot: PublicActivitySnapshot;
  sessionToken: string | null;
}) {
  const science = FACILITY_DISCIPLINES[item.facility.id];
  const isAvailable = item.accessMode === "read-only";
  const isLocked = item.availability === "locked";

  return (
    <>
      <nav className="access-breadcrumb" aria-label="Breadcrumb">
        <ol>
          <li>
            <a href={activityHref("/facilities", route)}>Facilities</a>
          </li>
          <li aria-current="page">{item.facility.name}</li>
        </ol>
      </nav>
      <AccessHeader
        eyebrow={`Facility ${String(item.facility.order).padStart(2, "0")} · ${science.discipline}`}
        title={item.facility.name}
        description={science.description}
      >
        <AccessState
          label={
            isAvailable
              ? "Read-only console available"
              : isLocked
                ? "Access locked"
                : "Access unknown"
          }
          tone={isAvailable ? "available" : isLocked ? "locked" : "unknown"}
        />
      </AccessHeader>

      {isAvailable ? (
        <FacilityScienceLab
          facilityId={item.facility.id}
          sessionToken={sessionToken}
        />
      ) : null}

      <details className="facility-orientation-details" open={!isAvailable}>
        <summary>
          {isAvailable
            ? "Position access, provenance, and solo workflow"
            : "Facility access state"}
        </summary>
        <div className="facility-console-layout">
        <FacilitySchematic facilityId={item.facility.id} />
        <section className="facility-console" aria-labelledby="console-state-title">
          <p className="eyebrow">Published access boundary</p>
          <h2 id="console-state-title">
            {isAvailable
              ? "Scientific access console"
              : isLocked
                ? "Console not yet available"
                : "Console state is not authoritative"}
          </h2>

          {isAvailable ? (
            <>
              <p>
                The signed projection permits this read-only facility bench.
                Orientation records and analysis controls are available below.
                Position evidence remains bound to its signed publication.{" "}
                Opening a console does not move your player or change investigation state.
              </p>
              {item.facility.id === "boundary_array" ? (
                <p className="access-capability-note">
                  The production clock-alignment method is implemented for
                  Boundary Array and can be exercised against its orientation record.
                </p>
              ) : null}
              <a
                className="access-primary-action"
                href={`${activityHref("/", route)}#evidence`}
              >
                Open current shared evidence workspace
                <span aria-hidden="true"> →</span>
              </a>
              <p className="access-provenance-note">
                The shared publication retains its institution, position, and
                source provenance when opened from this console.
              </p>
              {snapshot.environment === "test" && item.facility.id === "boundary_array" ? (
                <section
                  className="access-workflow-guide"
                  aria-labelledby="boundary-workflow-title"
                >
                  <p className="eyebrow">Position 1 · solo-test guide</p>
                  <h3 id="boundary-workflow-title">
                    Complete the investigation, then obtain independent confirmation
                  </h3>
                  <ol>
                    {BOUNDARY_SOLO_WORKFLOW.map(({ role, task }) => (
                      <li key={`${role}-${task}`}>
                        <strong>{role}</strong>
                        <span>{task}</span>
                      </li>
                    ))}
                  </ol>
                  <p className="access-test-blocker" role="note">
                    One human may rotate through these temporary roles, but the
                    assessment author cannot confirm their own assessment. A
                    second test identity must confirm it before Position 1 can
                    complete. This test guide does not
                    execute those authoritative commands.
                  </p>
                </section>
              ) : null}
            </>
          ) : isLocked ? (
            <>
              <p>
                The signed public state marks this facility locked. This route
                intentionally reveals no facility evidence, privileged state,
                role controls, or movement controls.
              </p>
              <p className="access-lock-explanation">
                Access changes only through authoritative investigation
                progression; visiting a URL cannot bypass that boundary.
              </p>
            </>
          ) : (
            <>
              <p>
                No authoritative facility access is present in the current
                projection. Preview or missing state is not treated as
                permission, so this console cannot be entered.
              </p>
              <p className="access-lock-explanation">
                Refresh the signed state or select a facility explicitly marked
                available.
              </p>
            </>
          )}

          <dl className="facility-console-facts">
            <div>
              <dt>Position</dt>
              <dd>
                <a href={activityHref(`/positions/${item.position.slug}`, route)}>
                  {item.position.title}
                </a>
              </dd>
            </div>
            <div>
              <dt>Access mode</dt>
              <dd>{stateLabel(item.accessMode)}</dd>
            </div>
            <div>
              <dt>Published assignments</dt>
              <dd>{item.activeAssignments ?? "Unpublished"}</dd>
            </div>
            <div>
              <dt>Projection</dt>
              <dd>{stateLabel(model.projection)}</dd>
            </div>
          </dl>
        </section>
        </div>
      </details>
    </>
  );
}

function PositionCard({
  item,
  route,
}: {
  item: PositionAccessDisplay;
  route: ActivityRoute;
}) {
  const tone =
    item.progression === "available" || item.progression === "completed"
      ? "available"
      : item.progression;
  return (
    <li className={`position-access-card position-access-card-${tone}`}>
      <article>
        <div className="position-access-ordinal" aria-hidden="true">
          <span>{String(item.position.ordinal).padStart(2, "0")}</span>
          <i />
        </div>
        <div>
          <AccessState
            label={`${stateLabel(item.progression)}${item.isCurrent ? " · current" : ""}`}
            tone={tone}
          />
          <h2>{item.position.title}</h2>
          <p>{POSITION_SUMMARIES[item.position.id]}</p>
          <a href={activityHref(`/positions/${item.position.slug}`, route)}>
            Inspect position state
            <span aria-hidden="true"> →</span>
          </a>
        </div>
      </article>
    </li>
  );
}

function PositionsCatalogue({
  model,
  route,
}: {
  model: InvestigationAccessDisplayModel;
  route: ActivityRoute;
}) {
  return (
    <>
      <AccessHeader
        eyebrow="Investigation sequence"
        title="Position state"
        description="The six positions form an ordered scientific investigation. Published progression is shown separately from the permanent catalogue."
      >
        <div className="access-identity">
          <span>{model.packId}</span>
          <span>content {model.contentVersion}</span>
        </div>
      </AccessHeader>
      <p className="access-boundary-note" role="note">
        {model.disclaimer}
      </p>
      <ol className="position-access-sequence">
        {model.positions.map((item) => (
          <PositionCard key={item.position.id} item={item} route={route} />
        ))}
      </ol>
    </>
  );
}

function PositionDetail({
  item,
  model,
  route,
}: {
  item: PositionAccessDisplay;
  model: InvestigationAccessDisplayModel;
  route: ActivityRoute;
}) {
  const facility = model.facilities.find(
    ({ facility: candidate }) =>
      candidate.id === item.position.focusFacilityId,
  );
  const progressionTone =
    item.progression === "available" || item.progression === "completed"
      ? "available"
      : item.progression;

  return (
    <>
      <nav className="access-breadcrumb" aria-label="Breadcrumb">
        <ol>
          <li>
            <a href={activityHref("/positions", route)}>Positions</a>
          </li>
          <li aria-current="page">{item.position.title}</li>
        </ol>
      </nav>
      <AccessHeader
        eyebrow={`Position ${String(item.position.ordinal).padStart(2, "0")}`}
        title={item.position.title}
        description={POSITION_SUMMARIES[item.position.id]}
      >
        <AccessState
          label={`${stateLabel(item.progression)}${item.isCurrent ? " · current" : ""}`}
          tone={progressionTone}
        />
      </AccessHeader>

      <section className="position-state-shell" aria-labelledby="position-state-title">
        <div className="position-state-axis" aria-hidden="true">
          {model.positions.map(({ position }) => (
            <i
              key={position.id}
              className={
                position.ordinal <= item.position.ordinal ? "traced" : undefined
              }
            />
          ))}
        </div>
        <div>
          <p className="eyebrow">Signed public progression</p>
          <h2 id="position-state-title">
            {item.progression === "unpublished"
              ? "Progression not published"
              : `${stateLabel(item.progression)} position`}
          </h2>
          {item.progression === "locked" ? (
            <p>
              This position is visible in the sequence, but
              its signed progression is locked. The route contains no completion,
              unlock, role, or movement controls.
            </p>
          ) : item.progression === "unpublished" ? (
            <p>
              The current signed projection does not publish position
              progression. Unpublished is not the same as locked, available, or
              complete, and this page does not infer any of those states.
            </p>
          ) : (
            <p>
              This is a read-only statement of public progression. It cannot
              complete the position or change investigation authority.
            </p>
          )}

          <dl className="position-state-facts">
            <div>
              <dt>Progression</dt>
              <dd>{stateLabel(item.progression)}</dd>
            </div>
            <div>
              <dt>Console mode</dt>
              <dd>{stateLabel(item.consoleMode)}</dd>
            </div>
            <div>
              <dt>Focus facility</dt>
              <dd>
                {facility ? (
                  <a
                    href={activityHref(
                      `/facilities/${facility.facility.slug}`,
                      route,
                    )}
                  >
                    {facility.facility.name}
                  </a>
                ) : (
                  "Catalogue mismatch"
                )}
              </dd>
            </div>
            <div>
              <dt>Next position</dt>
              <dd>
                {item.position.nextPositionId
                  ? (model.positions.find(
                      ({ position }) =>
                        position.id === item.position.nextPositionId,
                    )?.position.title ?? "Catalogue mismatch")
                  : "Investigation terminus"}
              </dd>
            </div>
          </dl>
        </div>
      </section>
    </>
  );
}

function NotFound({
  route,
  resource,
}: {
  route: ActivityRoute;
  resource?: "facility" | "position";
}) {
  return (
    <section className="access-not-found" aria-labelledby="not-found-title">
      <p className="eyebrow">404 · Catalogue route not found</p>
      <h1 id="not-found-title">
        {resource ? `Unknown ${resource}` : "Unknown game page"}
      </h1>
      <p>
        This address does not identify a published catalogue entry. No access
        state or privileged data has been exposed.
      </p>
      <div className="access-not-found-actions">
        <a href={activityHref("/facilities", route)}>Browse facilities</a>
        <a href={activityHref("/positions", route)}>Browse positions</a>
      </div>
    </section>
  );
}

export function AccessView({
  route,
  snapshot,
  sessionToken,
  loading,
  warning,
  lastRefresh,
  onRefresh,
  archived = false,
}: AccessViewProps) {
  if (route.kind === "workspace" || route.kind === "cartography") {
    return null;
  }

  const publishedModel = buildAccessDisplayModel(snapshot);
  const model =
    import.meta.env.DEV && publishedModel.projection === "mock-preview"
      ? {
          ...publishedModel,
          facilities: publishedModel.facilities.map((item) => ({
            ...item,
            availability: "available" as const,
            accessMode: "read-only" as const,
          })),
          disclaimer:
            "Local development inspection is active. These read-only benches cannot change investigation state.",
        }
      : publishedModel;
  let content: ReactNode;

  switch (route.kind) {
    case "facilities":
      content = (
        <FacilitiesCatalogue
          model={model}
          route={route}
          snapshot={snapshot}
        />
      );
      break;
    case "facility": {
      const item = model.facilities.find(
        ({ facility }) => facility.slug === route.slug,
      );
      content = item ? (
        <FacilityDetail
          item={item}
          model={model}
          route={route}
          snapshot={snapshot}
          sessionToken={sessionToken}
        />
      ) : (
        <NotFound route={route} resource="facility" />
      );
      break;
    }
    case "positions":
      content = <PositionsCatalogue model={model} route={route} />;
      break;
    case "position": {
      const item = model.positions.find(
        ({ position }) => position.slug === route.slug,
      );
      content = item ? (
        <PositionDetail item={item} model={model} route={route} />
      ) : (
        <NotFound route={route} resource="position" />
      );
      break;
    }
    case "not-found":
      content = <NotFound route={route} />;
      break;
  }

  return (
    <div className="access-view" id="access-content" tabIndex={-1}>
      {content}
      <RefreshStatus
        loading={loading}
        warning={warning}
        lastRefresh={lastRefresh}
        onRefresh={onRefresh}
        authoritative={snapshot.source === "hypha"}
        archived={archived}
      />
    </div>
  );
}
