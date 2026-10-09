import { useEffect, useRef } from "react";

export const DISPLAY_REFRESH_RATES = [60, 75, 120, 144] as const;

export type DisplayRefreshRate =
  (typeof DISPLAY_REFRESH_RATES)[number];

const DISPLAY_REFRESH_STORAGE_KEY =
  "missing-interior:signal-laboratory-display-fps";

export function readSignalLaboratoryDisplayFps():
  DisplayRefreshRate {
  if (typeof window === "undefined") {
    return 60;
  }

  const parsed = Number.parseInt(
    window.localStorage.getItem(
      DISPLAY_REFRESH_STORAGE_KEY,
    ) ?? "",
    10,
  );

  return DISPLAY_REFRESH_RATES.includes(
    parsed as DisplayRefreshRate,
  )
    ? (parsed as DisplayRefreshRate)
    : 60;
}

export function storeSignalLaboratoryDisplayFps(
  value: DisplayRefreshRate,
): void {
  window.localStorage.setItem(
    DISPLAY_REFRESH_STORAGE_KEY,
    String(value),
  );
}

interface SignalLaboratoryOscilloscopeProps {
  primary: readonly number[];
  nextPrimary: readonly number[];
  secondary: readonly number[];
  nextSecondary: readonly number[];
  label: string;
  streaming: boolean;
  analysisRateHz: number;
  displayFps: DisplayRefreshRate;
}

function extent(
  values: readonly number[],
): [number, number] {
  if (values.length === 0) {
    return [-1, 1];
  }

  const minimum = Math.min(...values);
  const maximum = Math.max(...values);

  if (minimum === maximum) {
    return [minimum - 0.5, maximum + 0.5];
  }

  return [minimum, maximum];
}

function interpolateSeries(
  current: readonly number[],
  next: readonly number[],
  phase: number,
): number[] {
  if (current.length === 0) {
    return [];
  }

  return current.map((value, index) => {
    const target = next[index] ?? value;
    return value + (target - value) * phase;
  });
}

function linePath(
  values: readonly number[],
  domain: readonly [number, number],
): string {
  if (values.length === 0) {
    return "";
  }

  const [minimum, maximum] = domain;

  return values
    .map((value, index) => {
      const x =
        25 +
        (index / Math.max(1, values.length - 1)) * 590;

      const y =
        255 -
        ((value - minimum) /
          Math.max(0.000001, maximum - minimum)) *
          230;

      return (
        `${index === 0 ? "M" : "L"}` +
        `${x.toFixed(2)} ${y.toFixed(2)}`
      );
    })
    .join(" ");
}

function PlotGrid() {
  return (
    <g className="science-plot-grid" aria-hidden="true">
      {Array.from({ length: 9 }, (_, index) => (
        <path
          key={`vertical-${index}`}
          d={`M${20 + index * 75} 16V258`}
        />
      ))}

      {Array.from({ length: 6 }, (_, index) => (
        <path
          key={`horizontal-${index}`}
          d={`M20 ${18 + index * 47.6}H620`}
        />
      ))}
    </g>
  );
}

export function SignalLaboratoryOscilloscope({
  primary,
  nextPrimary,
  secondary,
  nextSecondary,
  label,
  streaming,
  analysisRateHz,
  displayFps,
}: SignalLaboratoryOscilloscopeProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const primaryRef = useRef<SVGPathElement | null>(null);
  const secondaryRef = useRef<SVGPathElement | null>(null);
  const sweepRef = useRef<SVGLineElement | null>(null);

  useEffect(() => {
    const svg = svgRef.current;

    if (svg === null) {
      return;
    }

    const domain = extent([
      ...primary,
      ...nextPrimary,
      ...secondary,
      ...nextSecondary,
    ]);

    const frameDuration =
      1_000 / Math.max(0.001, analysisRateHz);

    const displayInterval = 1_000 / displayFps;

    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    );

    let animationFrame = 0;
    let visible = true;
    let frameStartedAt = performance.now();
    let previousAnimationAt = performance.now();

    /*
     * The accumulator permits rates such as 60 FPS on a
     * 75 Hz display without reducing the result to 37.5 FPS.
     */
    let accumulatedDisplayTime = displayInterval;

    const paint = (
      phase: number,
      showSweep: boolean,
    ) => {
      const normalized = Math.min(
        1,
        Math.max(0, phase),
      );

      const interpolatedPrimary = interpolateSeries(
        primary,
        nextPrimary,
        normalized,
      );

      const interpolatedSecondary = interpolateSeries(
        secondary,
        nextSecondary,
        normalized,
      );

      primaryRef.current?.setAttribute(
        "d",
        linePath(interpolatedPrimary, domain),
      );

      secondaryRef.current?.setAttribute(
        "d",
        linePath(interpolatedSecondary, domain),
      );

      if (sweepRef.current !== null) {
        const x = 25 + normalized * 590;

        sweepRef.current.setAttribute("x1", String(x));
        sweepRef.current.setAttribute("x2", String(x));
        sweepRef.current.style.display =
          showSweep ? "" : "none";
      }
    };

    let observer: IntersectionObserver | null = null;

    if ("IntersectionObserver" in window) {
      observer = new IntersectionObserver(
        ([entry]) => {
          visible = entry?.isIntersecting ?? false;

          if (visible) {
            frameStartedAt = performance.now();
            accumulatedDisplayTime = displayInterval;
          }
        },
        {
          rootMargin: "120px",
          threshold: 0.01,
        },
      );

      observer.observe(svg);
    }

    const animate = (now: number) => {
      animationFrame =
        window.requestAnimationFrame(animate);

      const elapsedAnimationTime = Math.min(
        100,
        Math.max(0, now - previousAnimationAt),
      );

      previousAnimationAt = now;

      const active =
        streaming &&
        visible &&
        !document.hidden &&
        !reducedMotion.matches;

      if (!active) {
        paint(0, false);
        frameStartedAt = now;
        accumulatedDisplayTime = displayInterval;
        return;
      }

      accumulatedDisplayTime += elapsedAnimationTime;

      if (
        accumulatedDisplayTime + 0.25 <
        displayInterval
      ) {
        return;
      }

      /*
       * Only one display update is permitted per browser frame.
       * Delayed frames are never replayed as a burst.
       */
      accumulatedDisplayTime %= displayInterval;

      const phase = Math.min(
        1,
        (now - frameStartedAt) / frameDuration,
      );

      paint(phase, true);
    };

    paint(0, false);

    animationFrame =
      window.requestAnimationFrame(animate);

    return () => {
      window.cancelAnimationFrame(animationFrame);
      observer?.disconnect();
    };
  }, [
    analysisRateHz,
    displayFps,
    nextPrimary,
    nextSecondary,
    primary,
    secondary,
    streaming,
  ]);

  return (
    <svg
      ref={svgRef}
      viewBox="0 0 640 280"
      role="img"
      aria-label={
        `${label}. Display interpolation is capped at ` +
        `${displayFps} frames per second. Analysis frames ` +
        `update at ${analysisRateHz} hertz.`
      }
      className="signal-laboratory-oscilloscope"
    >
      <rect
        x="0"
        y="0"
        width="640"
        height="280"
        className="science-plot-field"
      />

      <PlotGrid />

      <path
        ref={primaryRef}
        className="science-line primary"
      />

      <path
        ref={secondaryRef}
        className="science-line secondary"
      />

      <line
        ref={sweepRef}
        x1="25"
        x2="25"
        y1="18"
        y2="254"
        className="signal-oscilloscope-sweep"
        aria-hidden="true"
      />
    </svg>
  );
}
