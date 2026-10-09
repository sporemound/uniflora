import {
  useEffect,
  useRef,
  useState,
} from "react";

const SUPPORTED_REFRESH_RATES = [60, 75, 120, 144] as const;
const STORAGE_KEY = "missing-interior:scope-refresh-rate";
const SWEEP_DURATION_MS = 2_500;

type RefreshRate = (typeof SUPPORTED_REFRESH_RATES)[number];

interface ScopeBinding {
  svg: SVGSVGElement;
  paint: (phase: number) => void;
  showStatic: () => void;
  cleanup: () => void;
}

function isRefreshRate(value: number): value is RefreshRate {
  return SUPPORTED_REFRESH_RATES.includes(value as RefreshRate);
}

function storedRefreshRate(): RefreshRate {
  if (typeof window === "undefined") {
    return 60;
  }

  const parsed = Number.parseInt(
    window.localStorage.getItem(STORAGE_KEY) ?? "",
    10,
  );

  return isRefreshRate(parsed) ? parsed : 60;
}

function createScopeBinding(svg: SVGSVGElement): ScopeBinding {
  const nativeViewBox = svg.viewBox.baseVal;
  const fallbackBounds = svg.getBoundingClientRect();

  const minX = nativeViewBox.width > 0 ? nativeViewBox.x : 0;
  const minY = nativeViewBox.height > 0 ? nativeViewBox.y : 0;
  const width =
    nativeViewBox.width > 0
      ? nativeViewBox.width
      : Math.max(1, fallbackBounds.width);
  const height =
    nativeViewBox.height > 0
      ? nativeViewBox.height
      : Math.max(1, fallbackBounds.height);

  const namespace = "http://www.w3.org/2000/svg";
  const identifier = `scope-sweep-${Math.random()
    .toString(36)
    .slice(2)}`;

  const definitions = document.createElementNS(namespace, "defs");
  definitions.dataset.scopePlayback = "true";

  const clipPath = document.createElementNS(namespace, "clipPath");
  clipPath.id = identifier;
  clipPath.setAttribute("clipPathUnits", "userSpaceOnUse");

  const revealRect = document.createElementNS(namespace, "rect");
  revealRect.setAttribute("x", String(minX));
  revealRect.setAttribute("y", String(minY));
  revealRect.setAttribute("width", "0");
  revealRect.setAttribute("height", String(height));

  clipPath.append(revealRect);
  definitions.append(clipPath);
  svg.insertBefore(definitions, svg.firstChild);

  const sweepLine = document.createElementNS(namespace, "line");
  sweepLine.classList.add("scope-sweep-line");
  sweepLine.dataset.scopePlayback = "true";
  sweepLine.setAttribute("x1", String(minX));
  sweepLine.setAttribute("x2", String(minX));
  sweepLine.setAttribute("y1", String(minY));
  sweepLine.setAttribute("y2", String(minY + height));
  sweepLine.setAttribute("aria-hidden", "true");
  svg.append(sweepLine);

  const traceNodes = Array.from(
    svg.querySelectorAll<SVGGraphicsElement>(
      [
        ".waveform-line",
        ".uncertainty-band",
        ".quality-region",
      ].join(", "),
    ),
  );

  const previousClipPaths = traceNodes.map((node) => ({
    node,
    value: node.getAttribute("clip-path"),
  }));

  for (const node of traceNodes) {
    node.setAttribute("clip-path", `url(#${identifier})`);
  }

  return {
    svg,

    paint(phase: number): void {
      const normalizedPhase = Math.min(1, Math.max(0, phase));
      const sweepX = minX + width * normalizedPhase;

      revealRect.setAttribute(
        "width",
        String(width * normalizedPhase),
      );
      sweepLine.setAttribute("x1", String(sweepX));
      sweepLine.setAttribute("x2", String(sweepX));
      sweepLine.style.display = "";
    },

    showStatic(): void {
      revealRect.setAttribute("width", String(width));
      sweepLine.style.display = "none";
    },

    cleanup(): void {
      for (const previous of previousClipPaths) {
        if (previous.value === null) {
          previous.node.removeAttribute("clip-path");
        } else {
          previous.node.setAttribute(
            "clip-path",
            previous.value,
          );
        }
      }

      sweepLine.remove();
      definitions.remove();
    },
  };
}

export function OscilloscopeRefreshController() {
  const controllerRef = useRef<HTMLDivElement | null>(null);
  const statusRef = useRef<HTMLOutputElement | null>(null);

  const [targetFps, setTargetFps] = useState<RefreshRate>(
    storedRefreshRate,
  );
  const [running, setRunning] = useState(true);
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    const media = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    );

    const applyPreference = () => {
      setReducedMotion(media.matches);

      if (media.matches) {
        setRunning(false);
      }
    };

    applyPreference();
    media.addEventListener("change", applyPreference);

    return () => {
      media.removeEventListener("change", applyPreference);
    };
  }, []);

  useEffect(() => {
    const controller = controllerRef.current;
    const workspace = controller?.closest(".science-workspace");

    if (!(workspace instanceof HTMLElement)) {
      return;
    }

    let binding: ScopeBinding | null = null;
    let animationFrame = 0;
    let intersecting = true;
    let pausedStateApplied = false;

    let lastPaintAt = 0;
    let sweepStartedAt = performance.now();
    let measuredAt = performance.now();
    let measuredFrames = 0;

    const targetInterval = 1_000 / targetFps;

    const bindCurrentSvg = () => {
      const svg =
        workspace.querySelector<SVGSVGElement>(".waveform-svg");

      if (binding?.svg === svg) {
        return;
      }

      binding?.cleanup();
      binding = svg ? createScopeBinding(svg) : null;
      pausedStateApplied = false;
    };

    bindCurrentSvg();

    const mutationObserver = new MutationObserver(() => {
      bindCurrentSvg();
    });

    mutationObserver.observe(workspace, {
      childList: true,
      subtree: true,
    });

    const intersectionObserver = new IntersectionObserver(
      ([entry]) => {
        intersecting = entry?.isIntersecting ?? false;
      },
      {
        rootMargin: "120px",
        threshold: 0.01,
      },
    );

    const waveformCard =
      workspace.querySelector(".waveform-card") ?? workspace;

    intersectionObserver.observe(waveformCard);

    const setStatus = (value: string) => {
      if (statusRef.current !== null) {
        statusRef.current.textContent = value;
      }
    };

    const tick = (now: number) => {
      animationFrame = window.requestAnimationFrame(tick);

      const animationAllowed =
        running &&
        !reducedMotion &&
        !document.hidden &&
        intersecting;

      if (!animationAllowed) {
        if (!pausedStateApplied) {
          binding?.showStatic();
          pausedStateApplied = true;
        }

        lastPaintAt = now;
        sweepStartedAt = now;
        measuredAt = now;
        measuredFrames = 0;

        setStatus(
          reducedMotion
            ? "Static: reduced motion"
            : running
              ? "Paused offscreen"
              : "Paused",
        );
        return;
      }

      pausedStateApplied = false;

      /*
       * requestAnimationFrame follows the physical display.
       * This interval only caps rendering below that display rate.
       * Never execute catch-up frames after a delayed callback.
       */
      if (now - lastPaintAt < targetInterval - 0.25) {
        return;
      }

      lastPaintAt = now;

      const phase =
        ((now - sweepStartedAt) % SWEEP_DURATION_MS) /
        SWEEP_DURATION_MS;

      binding?.paint(phase);
      measuredFrames += 1;

      const measurementDuration = now - measuredAt;

      if (measurementDuration >= 1_000) {
        const measuredFps =
          (measuredFrames * 1_000) / measurementDuration;

        setStatus(
          `${Math.round(measuredFps)} rendered / ${targetFps} cap`,
        );

        measuredAt = now;
        measuredFrames = 0;
      }
    };

    animationFrame = window.requestAnimationFrame(tick);

    return () => {
      window.cancelAnimationFrame(animationFrame);
      mutationObserver.disconnect();
      intersectionObserver.disconnect();
      binding?.cleanup();
    };
  }, [targetFps, running, reducedMotion]);

  const changeRefreshRate = (
    event: React.ChangeEvent<HTMLSelectElement>,
  ) => {
    const parsed = Number.parseInt(event.target.value, 10);

    if (!isRefreshRate(parsed)) {
      return;
    }

    setTargetFps(parsed);
    window.localStorage.setItem(STORAGE_KEY, String(parsed));
  };

  return (
    <div
      ref={controllerRef}
      className="scope-refresh-controller"
      aria-label="Oscilloscope display refresh"
    >
      <label>
        <span>Scope refresh</span>
        <select
          value={targetFps}
          onChange={changeRefreshRate}
          aria-label="Oscilloscope maximum frames per second"
        >
          {SUPPORTED_REFRESH_RATES.map((fps) => (
            <option key={fps} value={fps}>
              {fps} FPS
            </option>
          ))}
        </select>
      </label>

      <button
        type="button"
        onClick={() => setRunning((value) => !value)}
        disabled={reducedMotion}
        title={
          reducedMotion
            ? "Animation is disabled by the system reduced-motion preference."
            : undefined
        }
      >
        {running ? "Pause scope" : "Run scope"}
      </button>

      <output
        ref={statusRef}
        className="scope-refresh-status"
        aria-live="polite"
      >
        Initializing
      </output>

      <small>
        Display playback only; scientific samples are unchanged.
      </small>
    </div>
  );
}
