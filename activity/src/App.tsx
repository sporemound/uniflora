import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AccessView } from "./components/AccessView";
import { CartographyView } from "./components/CartographyView";
import { GameConsole } from "./components/GameConsole";
import { InstitutionNetwork } from "./components/InstitutionNetwork";
import { HyphaVoiceConsole, type GuidanceMode } from "./components/HyphaVoiceConsole";
import { MetricCard } from "./components/MetricCard";
import { PrimaryNavigation } from "./components/PrimaryNavigation";
import { PublicRecordTimeline } from "./components/PublicRecordTimeline";
import { ScientificWorkspace } from "./components/ScientificWorkspace";
import { SiteSignIn } from "./components/SiteSignIn";
import { loadPublicSnapshot, type SnapshotOrigin } from "./lib/api";
import {
  currentAnalysisMapLayers,
  subscribeAnalysisMapLayers,
} from "./lib/analysis-layer-bus";
import { AudioConsole } from "./lib/audio";
import { classifyActivityLink } from "./lib/activity-link-navigation";
import { activityHref, parseActivityRoute } from "./lib/routes";
import { loadLatestScientificBundle } from "./lib/science";
import { connectSite, signOut, type SiteConnectionState } from "./lib/site-auth";
import {
  MOCK_PUBLIC_STATE,
  type EnvironmentName,
  type PublicActivitySnapshot,
} from "./shared/public-state";
import type { ScientificBundle } from "./shared/scientific-visualization";
import type { PublicAnomalyMapLayer } from "./shared/geospatial";

const WORKSPACE_SECTIONS = [
  {
    id: "overview",
    step: "01",
    label: "Overview",
    detail: "Position and team",
  },
  {
    id: "evidence",
    step: "02",
    label: "Evidence",
    detail: "Inspect the signal",
  },
  {
    id: "findings",
    step: "03",
    label: "Findings",
    detail: "Save and peer review",
  },
  {
    id: "publication",
    step: "04",
    label: "Outcome",
    detail: "Publication and next step",
  },
] as const;

type WorkspaceSectionId = (typeof WORKSPACE_SECTIONS)[number]["id"];
type PreviewServices = {
  status: "checking" | "ready" | "error";
  emailReady: boolean;
  chatReadReady: boolean;
  chatReady: boolean;
  demoReady: boolean;
  gameActionsReady: boolean;
};
const LIVE_ENVIRONMENT_ENABLED =
  import.meta.env.VITE_ENABLE_LIVE_ENVIRONMENT === "true";
const PREVIEW_ONLY = import.meta.env.VITE_PREVIEW_ONLY === "true";
const PUBLIC_LIVE_ENABLED = LIVE_ENVIRONMENT_ENABLED || PREVIEW_ONLY;
const PREVIEW_NEXT_REQUIREMENT =
  "Choose one permanent investigative role when game participation opens.";
const WORKING_NAME_STORAGE_KEY = "missing-interior:working-name";
const GUIDANCE_STORAGE_PREFIX = "missing-interior:activity-guidance:v1";
const UFOSINT_LAUNCH_CUSTOM_ID = /^ufosint:[1-9][0-9]{0,18}$/u;

function statusText(status: string): string {
  return status.replaceAll("-", " ");
}

function clockTime(date: Date, timeZone: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function defaultEnvironment(): EnvironmentName {
  if (PREVIEW_ONLY) return "live";
  const requested = new URLSearchParams(window.location.search).get("environment");

  if (
    requested === "test" ||
    (PUBLIC_LIVE_ENABLED && requested === "live")
  ) {
    return requested;
  }
  return LIVE_ENVIRONMENT_ENABLED &&
    import.meta.env.VITE_DEFAULT_ENVIRONMENT === "live"
    ? "live"
    : "test";
}

function activityLaunchUrl(customId: string | null): URL | null {
  if (!customId || !UFOSINT_LAUNCH_CUSTOM_ID.test(customId)) {
    return null;
  }
  const current = new URL(window.location.href);
  const next = new URL(current.href);
  next.pathname = "/cartography";
  next.hash = "";
  const requestedEnvironment = current.searchParams.get("environment");
  if (requestedEnvironment === "live" && !PUBLIC_LIVE_ENABLED) {
    next.searchParams.set("environment", "test");
  }
  next.searchParams.set("sidequest", customId);
  return next;
}

export default function App({ onShowDisclaimer }: { onShowDisclaimer: () => void }) {
    const [route, setRoute] = useState(() =>
      parseActivityRoute(window.location),
    );
    const [environment, setEnvironment] =
      useState<EnvironmentName>(defaultEnvironment());
    const [snapshot, setSnapshot] =
      useState<PublicActivitySnapshot>(MOCK_PUBLIC_STATE);
    const [snapshotOrigin, setSnapshotOrigin] =
      useState<SnapshotOrigin | "checking">("checking");
    const [warning, setWarning] = useState<string | null>(null);
    const [linkError, setLinkError] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [lastRefresh, setLastRefresh] = useState<string>("not yet refreshed");
    const [scienceBundle, setScienceBundle] = useState<ScientificBundle | null>(null);
    const [scienceWarning, setScienceWarning] = useState<string | null>(null);
    const [scienceLoading, setScienceLoading] = useState(true);
    const [activeSection, setActiveSection] =
      useState<WorkspaceSectionId>("overview");
    const [discord, setDiscord] = useState<SiteConnectionState>({
      status: "connecting",
      detail: "Checking your sign-in status.",
      participant: null,
      sessionToken: null,
      instanceId: null,
      launchCustomId: null,
    });
    const [previewServices, setPreviewServices] = useState<PreviewServices>({
      status: "checking",
      emailReady: false,
      chatReadReady: false,
      chatReady: false,
      demoReady: false,
      gameActionsReady: false,
    });
    const [workingName, setWorkingName] = useState(() =>
      window.localStorage.getItem(WORKING_NAME_STORAGE_KEY)?.trim() ?? "",
    );
    const [savedWorkingName, setSavedWorkingName] = useState(() =>
      window.localStorage.getItem(WORKING_NAME_STORAGE_KEY)?.trim() ?? "",
    );
    const [guidanceMode, setGuidanceMode] = useState<GuidanceMode>("standard");
    const [currentTime, setCurrentTime] = useState(() => new Date());
    const [analysisMapLayers, setAnalysisMapLayers] = useState<
      PublicAnomalyMapLayer[]
    >(() => currentAnalysisMapLayers());
    const snapshotRequestRevision = useRef(0);
    const scienceRequestRevision = useRef(0);
    const guidanceStorageKey = `${GUIDANCE_STORAGE_PREFIX}:${environment}:` +
      (discord.status === "ready" ? discord.participant.participantId : "preview");

    useEffect(() => {
      const timer = window.setInterval(() => setCurrentTime(new Date()), 30_000);
      return () => window.clearInterval(timer);
    }, []);

    useEffect(() => {
      const saved = window.localStorage.getItem(guidanceStorageKey);
      setGuidanceMode(saved === "guided" || saved === "expert" ? saved : "standard");
    }, [guidanceStorageKey]);

    const chooseGuidance = (mode: GuidanceMode) => {
      window.localStorage.setItem(guidanceStorageKey, mode);
      setGuidanceMode(mode);
    };

    const routeLaunchCustomId = useCallback((customId: string | null) => {
      const destination = activityLaunchUrl(customId);
      if (!destination) {
        return;
      }
      window.history.replaceState(
        null,
        "",
        `${destination.pathname}${destination.search}`,
      );
      window.dispatchEvent(new PopStateEvent("popstate"));
    }, []);

    const checkPreviewServices = useCallback(async () => {
      if (!PREVIEW_ONLY) return;
      try {
        const response = await fetch("/api/health", { cache: "no-store" });
        if (!response.ok) throw new Error(`Readiness check failed (${response.status}).`);
        const health = await response.json() as {
          emailReady?: unknown;
          chatReadReady?: unknown;
          chatReady?: unknown;
          demoReady?: unknown;
          gameActionsReady?: unknown;
        };
        setPreviewServices({
          status: "ready",
          emailReady: health.emailReady === true,
          chatReadReady: health.chatReadReady === true,
          chatReady: health.chatReady === true,
          demoReady: health.demoReady === true,
          gameActionsReady: health.gameActionsReady === true,
        });
      } catch {
        setPreviewServices({ status: "error", emailReady: false, chatReadReady: false, chatReady: false, demoReady: false, gameActionsReady: false });
      }
    }, []);

    useEffect(() => {
      if (!PREVIEW_ONLY) return;
      void checkPreviewServices();
      const checkOnFocus = () => {
        if (!document.hidden) void checkPreviewServices();
      };
      const timer = window.setInterval(checkOnFocus, 30_000);
      window.addEventListener("focus", checkOnFocus);
      return () => {
        window.clearInterval(timer);
        window.removeEventListener("focus", checkOnFocus);
      };
    }, [checkPreviewServices]);

    useEffect(
      () => subscribeAnalysisMapLayers(setAnalysisMapLayers),
      [],
    );

    const refreshSnapshot = useCallback(async () => {
      const requestRevision = ++snapshotRequestRevision.current;
      setLoading(true);
      const result = await loadPublicSnapshot(environment);
      if (requestRevision !== snapshotRequestRevision.current) {
        return;
      }
      setSnapshot(result.snapshot);
      setSnapshotOrigin(result.origin);
      setWarning(result.warning);
      setLastRefresh(new Date().toISOString());
      setLoading(false);
    }, [environment]);

    const refreshScience = useCallback(async () => {
      const requestRevision = ++scienceRequestRevision.current;
      setScienceLoading(true);
      try {
        const bundle = await loadLatestScientificBundle(environment);
        if (requestRevision !== scienceRequestRevision.current) {
          return;
        }
        setScienceBundle(bundle);
        setScienceWarning(
          bundle?.delivery === "bundled-test"
            ? "Using the immutable bundled test fixture; dynamic artifact storage is disabled in strict-free mode."
            : bundle
              ? null
              : `No Phase 3B scientific publication is registered in ${environment}.`,
        );
      } catch (error) {
        if (requestRevision !== scienceRequestRevision.current) {
          return;
        }
        const detail = error instanceof Error ? error.message : "Unknown scientific-publication failure.";
        setScienceBundle(null);
        setScienceWarning(`Interactive scientific projection unavailable: ${detail}`);
      } finally {
        if (requestRevision === scienceRequestRevision.current) {
          setScienceLoading(false);
        }
      }
    }, [environment]);

    useEffect(() => {
      let active = true;
      let revision = 0;
      const checkSession = () => {
        const currentRevision = ++revision;
        void connectSite(PREVIEW_ONLY).then((result) => {
          if (active && currentRevision === revision) {
            setDiscord(result);
            if (result.status === "ready") {
              setWorkingName((current) => current || result.participant.displayName);
              if (result.environment === "test" || PUBLIC_LIVE_ENABLED) {
                setEnvironment(result.environment);
                const url = new URL(window.location.href);
                url.searchParams.set("environment", result.environment);
                window.history.replaceState(null, "", url);
                setRoute(parseActivityRoute(url));
              }
              routeLaunchCustomId(result.launchCustomId);
            }
          }
        });
      };
      checkSession();
      const checkVisibleSession = () => {
        if (!document.hidden) checkSession();
      };
      window.addEventListener("focus", checkVisibleSession);
      document.addEventListener("visibilitychange", checkVisibleSession);
      return () => {
        active = false;
        window.removeEventListener("focus", checkVisibleSession);
        document.removeEventListener("visibilitychange", checkVisibleSession);
      };
    }, [routeLaunchCustomId]);

    useEffect(() => {
      const updateRoute = () => {
        const url = new URL(window.location.href);
        if (PREVIEW_ONLY && url.searchParams.get("environment") !== "live") {
          url.searchParams.set("environment", "live");
          window.history.replaceState(null, "", url);
        }
        setRoute(parseActivityRoute(url));
        const requestedEnvironment = new URLSearchParams(
          url.search,
        ).get("environment");
        if (PREVIEW_ONLY) {
          setEnvironment("live");
        } else if (discord.status === "ready") {
          setEnvironment(discord.environment);
        } else if (
          requestedEnvironment === "test" ||
          (PUBLIC_LIVE_ENABLED && requestedEnvironment === "live")
        ) {
          setEnvironment(requestedEnvironment);
        } else if (!PUBLIC_LIVE_ENABLED) {
          setEnvironment("test");
        }
      };
      window.addEventListener("popstate", updateRoute);
      return () => window.removeEventListener("popstate", updateRoute);
    }, [discord]);

    useEffect(() => {
      const navigateWithinActivity = (event: MouseEvent) => {
        const target = event.target;
        if (!(target instanceof Element)) {
          return;
        }

        const anchor = target.closest<HTMLAnchorElement>("a[href]");
        if (!anchor) {
          return;
        }

        const decision = classifyActivityLink({
          currentHref: window.location.href,
          href: anchor.href,
          runtime: "browser-preview",
          target: anchor.target,
          download: anchor.hasAttribute("download"),
          button: event.button,
          defaultPrevented: event.defaultPrevented,
          metaKey: event.metaKey,
          ctrlKey: event.ctrlKey,
          shiftKey: event.shiftKey,
          altKey: event.altKey,
        });
        if (decision.intent === "ignore" || decision.intent === "browser-default") {
          return;
        }

        event.preventDefault();
        if (decision.intent === "blocked") {
          setLinkError("That destination was blocked because external links must use safe HTTPS URLs.");
          return;
        }
        if (decision.intent === "discord-external") return;

        setLinkError(null);
        const currentHistoryHref =
          `${window.location.pathname}${window.location.search}${window.location.hash}`;
        if (decision.historyHref !== currentHistoryHref) {
          window.history.pushState(null, "", decision.historyHref);
        }
        window.dispatchEvent(new PopStateEvent("popstate"));

        window.requestAnimationFrame(() => {
          window.requestAnimationFrame(() => {
            let fragment = decision.fragment;
            try {
              fragment = decodeURIComponent(fragment);
            } catch {
              // Retain the literal fragment when it is not valid URI encoding.
            }
            const fragmentTarget = fragment
              ? document.getElementById(fragment)
              : null;
            if (fragmentTarget) {
              fragmentTarget.scrollIntoView();
            } else {
              window.scrollTo({ top: 0, left: 0, behavior: "auto" });
            }
          });
        });
      };

      document.addEventListener("click", navigateWithinActivity, true);
      return () => document.removeEventListener("click", navigateWithinActivity, true);
    }, []);

    useEffect(() => {
      const url = new URL(window.location.href);
      if (PREVIEW_ONLY) {
        if (url.searchParams.get("environment") !== "live") {
          url.searchParams.set("environment", "live");
          window.history.replaceState(null, "", url);
          setRoute(parseActivityRoute(url));
        }
        return;
      }
      if (PUBLIC_LIVE_ENABLED) {
        return;
      }
      if (url.searchParams.get("environment") === "live") {
        url.searchParams.set("environment", "test");
        window.history.replaceState(null, "", url);
        setRoute(parseActivityRoute(url));
      }
    }, []);

    useEffect(() => {
      setLoading(true);
      setSnapshotOrigin("checking");
      void refreshSnapshot();
      const snapshotTimer = window.setInterval(() => {
        void refreshSnapshot();
      }, 10_000);
      return () => {
        window.clearInterval(snapshotTimer);
        snapshotRequestRevision.current += 1;
      };
    }, [refreshSnapshot]);

    useEffect(() => {
      if (route.kind !== "workspace") {
        setScienceLoading(false);
        scienceRequestRevision.current += 1;
        return;
      }
      setScienceLoading(true);
      void refreshScience();
      const scienceTimer = window.setInterval(() => {
        void refreshScience();
      }, 15_000);
      return () => {
        window.clearInterval(scienceTimer);
        scienceRequestRevision.current += 1;
      };
    }, [refreshScience, route.kind]);

    useEffect(() => {
      if (route.kind !== "workspace") {
        return;
      }

      let animationFrame = 0;

      const updateActiveSection = () => {
        window.cancelAnimationFrame(animationFrame);
        animationFrame = window.requestAnimationFrame(() => {
          const navigationLine = Math.min(window.innerHeight * 0.32, 260);
          let nextSection: WorkspaceSectionId = "overview";

          for (const section of WORKSPACE_SECTIONS) {
            const target = document.getElementById(section.id);
            if (target && target.getBoundingClientRect().top <= navigationLine) {
              nextSection = section.id;
            }
          }

          setActiveSection(nextSection);
        });
      };

      updateActiveSection();
      window.addEventListener("scroll", updateActiveSection, { passive: true });
      window.addEventListener("resize", updateActiveSection);
      return () => {
        window.cancelAnimationFrame(animationFrame);
        window.removeEventListener("scroll", updateActiveSection);
        window.removeEventListener("resize", updateActiveSection);
      };
    }, [route.kind, scienceBundle]);

    useEffect(() => {
      const pageTitle =
        route.kind === "cartography"
          ? "Network Cartography · The Missing Interior"
          : route.kind === "facilities" || route.kind === "facility"
          ? "Facility Access · The Missing Interior"
          : route.kind === "positions" || route.kind === "position"
            ? "Position State · The Missing Interior"
            : route.kind === "not-found"
              ? "Page Not Found · The Missing Interior"
              : "The Missing Interior";
      document.title = pageTitle;
    }, [route.kind]);

    const focusLocation = useMemo(
      () => snapshot.locations.find(({ id }) => id === snapshot.focusLocationId),
      [snapshot],
    );
    const adaptivePresentation =
      snapshot.schemaVersion === "2.2.0" ||
      snapshot.schemaVersion === "2.3.0" ||
      snapshot.schemaVersion === "2.4.0"
        ? snapshot.adaptivePresentation
        : null;
    const accessDetail = PREVIEW_ONLY && discord.status === "signed-out" &&
      previewServices.status === "ready" && !previewServices.emailReady
      ? "Email sign-in is being configured for this preview."
      : discord.detail;
    const publicRecordTimeline = environment === "live" ? (
      <PublicRecordTimeline
        origin={snapshotOrigin}
        archiveUpdatedAt={snapshotOrigin === "archived" ? snapshot.updatedAt : ""}
      />
    ) : null;

    return (
      <>
      <a
        className="skip-link"
        href={
          route.kind === "workspace"
            ? "#overview"
            : route.kind === "cartography"
              ? "#cartography-content"
              : "#access-content"
        }
        onClick={(event) => {
          event.preventDefault();
          const targetId =
            route.kind === "workspace"
              ? "overview"
              : route.kind === "cartography"
                ? "cartography-content"
                : "access-content";
          const target = document.getElementById(targetId);
          if (!target) {
            return;
          }
          target.scrollIntoView({ block: "start" });
          target.focus({ preventScroll: true });
        }}
      >
        {route.kind === "workspace"
          ? "Skip to investigation overview"
          : route.kind === "cartography"
            ? "Skip to network cartography"
            : "Skip to access catalogue"}
      </a>
      <main className="app-shell" id="main-content">
        <header className="topbar">
          <div>
            <p className="eyebrow">Distributed analysis console</p>
            <h1>The Missing Interior</h1>
          </div>
          <div className="system-strip" aria-label="Personal guidance and connection status">
            <div className="difficulty-control" aria-label="Guidance options">
              <span>Game guidance</span>
              <div className="difficulty-options">
                {(["guided", "standard", "expert"] as const).map((mode) => (
                  <button key={mode} type="button" aria-pressed={guidanceMode === mode}
                    onClick={() => chooseGuidance(mode)}>
                    {mode[0].toUpperCase() + mode.slice(1)}
                  </button>
                ))}
              </div>
              <small>Controls hints and explanations in this game.</small>
            </div>
            {PUBLIC_LIVE_ENABLED && !PREVIEW_ONLY && discord.status !== "ready" ? (
              <label className="environment-control">
                <span>Public environment</span>
                <select
                  value={environment}
                  onChange={(event: { target: { value: string } }) => {
                    const nextEnvironment = event.target.value as EnvironmentName;
                    const url = new URL(window.location.href);
                    url.searchParams.set("environment", nextEnvironment);
                    window.history.replaceState(null, "", url);
                    setRoute(parseActivityRoute(url));
                    setEnvironment(nextEnvironment);
                  }}
                >
                  <option value="test">Test</option>
                  <option value="live">Live</option>
                </select>
              </label>
            ) : (
              <div className="environment-control environment-locked">
                <span>Campaign</span>
                <strong>{PREVIEW_ONLY
                  ? snapshotOrigin === "published" ? "Live public record"
                    : snapshotOrigin === "archived" ? "Captured case archive"
                      : snapshotOrigin === "checking" ? "Checking public record"
                        : "Public record unavailable"
                  : discord.status === "ready"
                  ? discord.environment === "live" ? "Live" : "Private test"
                  : discord.status === "connecting" ? "Connecting" : "Not connected"}</strong>
              </div>
            )}
            <div className="connection-readout" aria-label="Connection details">
              <span className={`connection-dot ${discord.status}`} />
              <span>{discord.status === "ready" ? "Signed in" : statusText(discord.status)}</span>
              <span>Now {clockTime(currentTime, "UTC")}Z</span>
              <span>{clockTime(currentTime, "America/Los_Angeles")} Pacific</span>
            </div>
            {discord.status === "error" ? (
              <p className="warning" role="alert">Sign-in: {discord.detail}</p>
            ) : null}
            {discord.status === "ready" ? (
              <button type="button" onClick={() => {
                void signOut().then(() => setDiscord({
                  status: "signed-out",
                  detail: "Sign in by email to join the investigation.",
                  participant: null,
                  sessionToken: null,
                  instanceId: null,
                  launchCustomId: null,
                })).catch((error: unknown) => setWarning(
                  error instanceof Error ? error.message : "Could not sign out.",
                ));
              }}>Sign out</button>
            ) : null}
          </div>
        </header>

        {PREVIEW_ONLY ? publicRecordTimeline : null}

        {discord.status === "signed-out" ? <SiteSignIn
          previewOnly={PREVIEW_ONLY}
          chatReadReady={previewServices.chatReadReady}
          chatReady={previewServices.chatReady}
          gameActionsReady={previewServices.gameActionsReady}
          emailReadiness={!PREVIEW_ONLY ? "ready" : previewServices.status === "error" ? "error" :
            previewServices.emailReady ? "ready" : previewServices.status === "checking" ? "checking" : "pending"}
          onRetryReadiness={() => {
            setPreviewServices((current) => ({ ...current, status: "checking" }));
            void checkPreviewServices();
          }}
        /> : null}
        {discord.status === "ready" && (!PREVIEW_ONLY || previewServices.gameActionsReady)
          ? <GameConsole onProgress={refreshSnapshot} />
          : PREVIEW_ONLY ? (
            <section className="game-console game-console-pending" role="status">
              <p className="eyebrow">Authoritative campaign</p>
              <h2>Game participation pending</h2>
              <p>{previewServices.gameActionsReady
                ? previewServices.emailReady
                  ? "Sign in by email to choose a permanent role and submit game actions."
                  : "The game engine is connected. Email sign-in is being configured before role selection opens."
                : "The hosted game engine is being connected. Everyone can read the public record while participation is prepared."}</p>
            </section>
          ) : null}
        <PrimaryNavigation route={route} />
        <AudioConsole routeKey={`${route.pathname}${route.search}`} hyphaTextOnly={PREVIEW_ONLY} />
        {linkError ? <p className="warning" role="alert">{linkError}</p> : null}
        <HyphaVoiceConsole
          sessionToken={discord.sessionToken}
          connectionStatus={discord.status}
          connectionDetail={accessDetail}
          workingName={savedWorkingName}
          environment={environment}
          snapshot={snapshot}
          guidanceMode={guidanceMode}
          previewOnly={PREVIEW_ONLY}
          snapshotOrigin={snapshotOrigin === "checking" ? "unavailable" : snapshotOrigin}
          previewReadiness={previewServices}
        />
        {!PREVIEW_ONLY ? publicRecordTimeline : null}

        {snapshotOrigin === "checking" || snapshotOrigin === "unavailable" ? (
          <section className="public-state-unavailable" role="status">
            <h2>{snapshotOrigin === "checking" ? "Loading public case state" : "Public case state unavailable"}</h2>
            <p>{snapshotOrigin === "checking"
              ? "Checking the published projection and captured archive."
              : warning ?? "The public projection could not be loaded. Please try again."}</p>
            {snapshotOrigin === "unavailable" ? (
              <button type="button" onClick={() => void refreshSnapshot()}>Retry public state</button>
            ) : null}
          </section>
        ) : route.kind === "workspace" ? (
          <>
        <nav
          className="workspace-nav"
          aria-label="Investigation workflow"
          aria-describedby="workspace-nav-guide"
        >
          <div className="workspace-nav-intro">
            <span>Workspace map</span>
            <p id="workspace-nav-guide">
              Read the briefing, inspect the evidence, review a finding, then check the outcome.
            </p>
          </div>
          <ol>
            {WORKSPACE_SECTIONS.map((section) => {
              const unavailable = section.id === "findings" && !scienceBundle;
              const label = (
                <>
                  <span className="workspace-nav-step" aria-hidden="true">{section.step}</span>
                  <span>
                    <strong>{section.label}</strong>
                    <small>{unavailable ? "Available with evidence" : section.detail}</small>
                  </span>
                </>
              );

              return (
                <li key={section.id}>
                  {unavailable ? (
                    <span className="workspace-nav-link unavailable" aria-disabled="true">
                      {label}
                    </span>
                  ) : (
                    <a
                      className="workspace-nav-link"
                      href={`#${section.id}`}
                      aria-current={activeSection === section.id ? "location" : undefined}
                      onClick={() => setActiveSection(section.id)}
                    >
                      {label}
                    </a>
                  )}
                </li>
              );
            })}
          </ol>
        </nav>

        <section
          className="position-banner"
          id="overview"
          tabIndex={-1}
          aria-labelledby="position-title"
        >
          <div>
            <p className="eyebrow">
              {snapshotOrigin === "archived" ? "Captured archive · " : "Published live state · "}
              {snapshot.positionId}
            </p>
            <h2 id="position-title">{snapshot.positionTitle}</h2>
            <p>
              Focus: <strong>{focusLocation?.name ?? "Unresolved"}</strong>
            </p>
          </div>
          <dl className="state-identity">
            <div>
              <dt>Revision</dt>
              <dd>{snapshot.revision}</dd>
            </div>
            <div>
              <dt>State head</dt>
              <dd>{snapshot.stateHeadHash}</dd>
            </div>
            <div>
              <dt>Previous</dt>
              <dd>{snapshot.previousStateHeadHash ?? "genesis"}</dd>
            </div>
            <div>
              <dt>Source</dt>
              <dd>{snapshot.source}</dd>
            </div>
            <div>
              <dt>Updated</dt>
              <dd>{snapshot.updatedAt}</dd>
            </div>
          </dl>
        </section>

        {adaptivePresentation ? (
          <section
            className={`adaptive-presentation ${adaptivePresentation.kind}`}
            aria-labelledby="adaptive-presentation-title"
          >
            <div className="adaptive-presentation-heading">
              <p className="eyebrow">
                {adaptivePresentation.kind === "ending"
                  ? "Final distributed record"
                  : "Facility intake memorandum"}
              </p>
              <h2 id="adaptive-presentation-title">
                {adaptivePresentation.kind === "ending"
                  ? "Observation window"
                  : focusLocation?.name ?? snapshot.positionTitle}
              </h2>
            </div>
            <div className="adaptive-prose">
              {adaptivePresentation.prose.split("\n").map((paragraph, index) =>
                paragraph.trim() ? <p key={index}>{paragraph}</p> : null,
              )}
            </div>
            {adaptivePresentation.guidance.length > 0 ? (
              <div className="adaptive-mechanics">
                <h3>Current working controls</h3>
                <ul>
                  {adaptivePresentation.guidance.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
                {adaptivePresentation.requiredActionId ? (
                  <p>
                    Required reconciliation:{" "}
                    <code>{adaptivePresentation.requiredActionId}</code>
                  </p>
                ) : null}
                {adaptivePresentation.optionalActionIds.length > 0 ? (
                  <p>
                    Optional analysis:{" "}
                    <code>{adaptivePresentation.optionalActionIds.join(", ")}</code>
                  </p>
                ) : null}
              </div>
            ) : null}
          </section>
        ) : null}

        {warning ? <p className="warning" role="status">{warning}</p> : null}
        <p className="sr-only" aria-live="polite">
          {loading
            ? `Loading ${environment} public activity state.`
            : `Public game state loaded. ${accessDetail}`}
        </p>

        <section className="metric-grid" aria-label="Position metrics">
          <MetricCard
            label="Active assignments"
            value={snapshot.metrics.activeAssignments}
            note="Campaign investigators"
            definition="Investigators with a permanent role or active facility assignment in the current game state."
          />
          <MetricCard
            label="Completed artifacts"
            value={snapshot.metrics.completedArtifacts}
            note="Verified analysis outputs"
            definition="Position assessments that have been confirmed in the event stream."
          />
          <MetricCard
            label="Contradictions"
            value={snapshot.metrics.unresolvedContradictions}
            note="Preserved, not reconciled"
            definition="Required contradictions for the current position that still need to be explicitly preserved."
          />
          <MetricCard
            label="Awaiting verification"
            value={snapshot.metrics.awaitingVerification}
            note="Requires another participant"
            definition="Position assessments still recorded as drafts and awaiting confirmation."
          />
        </section>

        <section className="primary-grid">
          <InstitutionNetwork
            locations={snapshot.locations}
            anomalyLayers={analysisMapLayers}
            cartographyHref={activityHref("/cartography", route)}
            previewOnly={PREVIEW_ONLY}
            archived={snapshotOrigin === "archived"}
          />

          <aside className="roster-panel" aria-labelledby="roster-heading">
            <div className="section-heading-row">
              <div>
                <p className="eyebrow">Current operational identities</p>
                <h2 id="roster-heading">Working-name roster</h2>
              </div>
            </div>

            <form
              className="working-name-form"
              onSubmit={(event) => {
                event.preventDefault();
                const normalized = workingName.trim().slice(0, 40);
                setWorkingName(normalized);
                setSavedWorkingName(normalized);
                if (normalized) {
                  window.localStorage.setItem(WORKING_NAME_STORAGE_KEY, normalized);
                } else {
                  window.localStorage.removeItem(WORKING_NAME_STORAGE_KEY);
                }
              }}
            >
              <label htmlFor="working-name">{PREVIEW_ONLY ? "Your chat display name" : "Your working name"}</label>
              <div>
                <input
                  id="working-name"
                  name="working-name"
                  value={workingName}
                  maxLength={40}
                  autoComplete="nickname"
                  placeholder={discord.participant?.displayName ?? "Enter a working name"}
                  onChange={(event) => setWorkingName(event.target.value)}
                />
                <button type="submit">Save</button>
              </div>
              <small>{PREVIEW_ONLY
                ? "Saved in this browser and shown with messages you post. It does not change the published roster."
                : "Saved only in this browser on this device."}</small>
            </form>

            {PREVIEW_ONLY ? (
              <p className="preview-roster-note">
                {snapshotOrigin === "archived" ? "Captured roster from the archive." : "Current published roster."}
                {" "}{previewServices.gameActionsReady && previewServices.emailReady
                  ? "Sign in to choose one permanent role: Evidence Investigator, Systems Analyst, or Independent Reviewer."
                  : "Permanent role selection will open when game participation is connected."}
              </p>
            ) : null}

            <ul className="roster-list">
              {snapshot.assignments.map((assignment) => (
                <li key={assignment.assignmentId}>
                  <span className={`role-mark ${assignment.paletteToken}`} aria-hidden="true" />
                  <div>
                    <strong>{assignment.workingName}</strong>
                    <span>{assignment.roleTitle}</span>
                    <small>{assignment.station}</small>
                  </div>
                  <span className={`assignment-status ${assignment.status}`}>
                    {statusText(assignment.status)}
                  </span>
                </li>
              ))}
            </ul>
          </aside>
        </section>

        <div className="workspace-section-anchor" id="evidence" tabIndex={-1}>
          {scienceWarning ? <p className="science-warning" role="status">{scienceWarning}</p> : null}
          {scienceBundle ? (
            <ScientificWorkspace
              bundle={scienceBundle}
              snapshot={snapshot}
              sessionToken={discord.sessionToken}
              discordInstanceId={discord.instanceId}
              previewOnly={PREVIEW_ONLY}
              archived={snapshotOrigin === "archived"}
            />
          ) : scienceLoading ? (
            <section className="science-workspace science-loading" aria-live="polite">
              Loading the latest interactive scientific projection…
            </section>
          ) : null}
        </div>

        <section className="lower-grid" id="publication" tabIndex={-1}>
          <article className="publication-panel" aria-labelledby="publication-heading">
            <div className="section-heading-row">
              <div>
                <p className="eyebrow">Latest scientific publication</p>
                <h2 id="publication-heading">
                  {snapshot.latestPublication?.title ?? "No publication available"}
                </h2>
              </div>
              {snapshot.latestPublication ? (
                <span className={`publication-status ${snapshot.latestPublication.status}`}>
                  {snapshot.latestPublication.status}
                </span>
              ) : null}
            </div>

            {snapshot.latestPublication ? (
              <>
                {snapshot.latestPublication.primaryAsset ? (
                  <figure className="publication-asset">
                    <img
                      src={snapshot.latestPublication.primaryAsset.url}
                      alt={`${snapshot.latestPublication.title}. ${snapshot.latestPublication.finding}`}
                    />
                    <figcaption>
                      {snapshot.latestPublication.primaryAsset.filename} · {snapshot.latestPublication.primaryAsset.byteLength.toLocaleString()} bytes
                    </figcaption>
                  </figure>
                ) : (
                  <div className="timing-figure" role="img" aria-label="Example packet timing reconstruction">
                    <div className="time-axis">
                      <span style={{ left: "12%" }}><i />03:17:06<br /><small>Array response</small></span>
                      <span style={{ left: "50%" }}><i />03:17:09<br /><small>Intake receipt</small></span>
                      <span style={{ left: "86%" }}><i />03:17:12<br /><small>Packet timestamp</small></span>
                    </div>
                  </div>
                )}
                <p className="finding"><strong>Finding.</strong> {snapshot.latestPublication.finding}</p>
                <p className="limitation"><strong>Limitation.</strong> {snapshot.latestPublication.limitation}</p>
                <p className="artifact-id">
                  {snapshot.latestPublication.publicationId} · {snapshot.latestPublication.artifactId}
                </p>
              </>
            ) : (
              <p>No public scientific artifact has been published for this state.</p>
            )}
          </article>

          <aside className="requirement-panel" aria-labelledby="requirement-heading">
            <p className="eyebrow">Next collaborative requirement</p>
            <h2 id="requirement-heading">The record remains open</h2>
            <p>{PREVIEW_ONLY && snapshotOrigin !== "published"
              ? PREVIEW_NEXT_REQUIREMENT
              : snapshot.nextRequirement}</p>
            <div className="connection-note">
              <span className={`connection-dot ${discord.status}`} />
              <div>
                <strong>{PREVIEW_ONLY ? "Access" : "Account"}</strong>
                <span>{accessDetail}</span>
                {discord.participant ? (
                  <span className="participant-id">{discord.participant.participantId}</span>
                ) : null}
              </div>
            </div>
            <div className="sync-note">
              <strong>{snapshotOrigin === "archived" ? "Captured-case refresh" : "Public-state refresh"}</strong>
              <span>{snapshotOrigin === "archived" ? "Archive captured" : "Game state published"} {snapshot.zuluTime} / {snapshot.facilityTime} {snapshot.facilityTimezone}</span>
              <span>{loading ? "Refreshing…" : `Last checked ${lastRefresh}`}</span>
              <button
                type="button"
                onClick={() => void Promise.all([refreshSnapshot(), refreshScience()])}
                disabled={loading || scienceLoading}
              >
                Refresh now
              </button>
            </div>
          </aside>
        </section>
          </>
        ) : route.kind === "cartography" ? (
          <CartographyView
            route={route}
            locations={snapshot.locations}
            anomalyLayers={analysisMapLayers}
            sessionToken={discord.sessionToken}
            participant={discord.participant}
            previewOnly={PREVIEW_ONLY}
          />
        ) : (
          <AccessView
            route={route}
            snapshot={snapshot}
            sessionToken={discord.sessionToken}
            loading={loading}
            warning={warning}
            lastRefresh={lastRefresh}
            onRefresh={refreshSnapshot}
            archived={snapshotOrigin === "archived"}
          />
        )}

        <footer>
          <span>Public scientific investigation workspace</span>
          <a className="footer-discord-link" href="https://discord.gg/FMGHE7Yee" target="_blank" rel="noopener noreferrer">Join the Uniflora Discord</a>
          <button className="footer-disclaimer-link" type="button" onClick={onShowDisclaimer}>
            Disclaimer &amp; important information
          </button>
          <span>{PREVIEW_ONLY
            ? snapshotOrigin === "published"
              ? previewServices.gameActionsReady && previewServices.emailReady
                ? "Live public record · game participation open"
                : "Live public record · game participation pending"
              : snapshotOrigin === "archived"
                ? previewServices.gameActionsReady && previewServices.emailReady
                  ? "Captured public case archive · game participation open"
                  : "Captured public case archive · game participation pending"
                : "Public record pending"
            : "Live campaign commands · public scientific projections · shared analysis rooms"}</span>
        </footer>
      </main>
      </>
    );
  }
