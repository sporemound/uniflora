import type { EnvironmentalFacilityId } from "../shared/environmental-context";
import type { FacilityScienceFrame } from "../shared/facility-science";

export const SCIENCE_SONIFICATION_LIMITS = Object.freeze({
  maximumDurationSeconds: 12,
  maximumEvents: 192,
  minimumFrequencyHz: 110,
  maximumFrequencyHz: 1_760,
  maximumGain: 0.18,
});

export type ScienceSonificationDatumStatus =
  | "observed"
  | "zero"
  | "missing"
  | "withheld";

export type ScienceSonificationSourceStatus =
  | "available"
  | "partial"
  | "missing"
  | "withheld";

export type ScienceSonificationWaveform =
  | "sine"
  | "triangle"
  | "square"
  | "sawtooth";

export interface ScienceSonificationRange {
  minimum: number;
  maximum: number;
}

export interface ScienceSonificationCoordinate {
  label: string;
  value: number;
  unit: string;
}

/**
 * Engine-neutral instructions for a tone or a deliberately silent data gap.
 * Consumers must not replace silent missing/withheld events with interpolated
 * values.
 */
export interface ScienceSonificationEvent {
  id: string;
  kind: "tone" | "silence";
  status: ScienceSonificationDatumStatus;
  startSeconds: number;
  durationSeconds: number;
  frequencyHz: number | null;
  gain: number;
  waveform: ScienceSonificationWaveform | null;
  sourceSeries: string;
  sourceIndex: number | null;
  sourceValue: number | null;
  sourceValueUnit: string;
  sourcePosition: ScienceSonificationCoordinate[];
}

export interface ScienceSonificationLegend {
  id: string;
  label: string;
  sourceSeries: string;
  sourceStatus: ScienceSonificationSourceStatus;
  sourceUnit: string;
  sourceDomain: ScienceSonificationRange | null;
  outputPitchHz: ScienceSonificationRange;
  outputTimeSeconds: ScienceSonificationRange;
  outputGain: ScienceSonificationRange;
  scale: "linear" | "logarithmic";
  pitchMapping: string;
  timeMapping: string;
  gainMapping: string;
  normalization: string;
  timeCompressionRatio: number | null;
  timeCompression: string;
  plainLanguage: string;
}

export interface ScienceSonificationStatusLegend {
  status: ScienceSonificationDatumStatus;
  visibleLabel: string;
  scheduleTreatment: string;
}

export interface ScienceSonificationAccessibility {
  optional: true;
  audioRequiredForProgression: false;
  visibleLegendRequired: true;
  textEquivalent: string;
}

export interface ScienceSonificationSchedule {
  status: "available" | "unavailable";
  unavailableReason: string | null;
  facilityId: EnvironmentalFacilityId;
  toolId: string;
  title: string;
  durationSeconds: number;
  events: ScienceSonificationEvent[];
  legends: ScienceSonificationLegend[];
  statusLegend: readonly ScienceSonificationStatusLegend[];
  accessibility: ScienceSonificationAccessibility;
}

export interface ScienceSonificationOptions {
  durationSeconds?: number;
  maxEvents?: number;
}

export const SUPPORTED_SCIENCE_SONIFICATION_TOOLS = Object.freeze({
  boundary_array: ["oscilloscope", "spectrum", "correlation"],
  subsurface_resonance_station: ["depthFrequency", "spectrum", "stations"],
} as const);

export const SCIENCE_SONIFICATION_STATUS_LEGEND: readonly ScienceSonificationStatusLegend[] =
  Object.freeze([
    Object.freeze({
      status: "observed",
      visibleLabel: "Recorded value",
      scheduleTreatment: "A tone represents the displayed finite value.",
    }),
    Object.freeze({
      status: "zero",
      visibleLabel: "Recorded zero",
      scheduleTreatment:
        "A quiet reference tone represents a real zero; it is not a missing sample.",
    }),
    Object.freeze({
      status: "missing",
      visibleLabel: "Missing value",
      scheduleTreatment:
        "A labeled silent gap is retained. No value is interpolated.",
    }),
    Object.freeze({
      status: "withheld",
      visibleLabel: "Withheld value",
      scheduleTreatment:
        "A labeled silent gap is retained. No substitute value is generated.",
    }),
  ]);

const ACCESSIBILITY: ScienceSonificationAccessibility = Object.freeze({
  optional: true,
  audioRequiredForProgression: false,
  visibleLegendRequired: true,
  textEquivalent:
    "Audio is an optional representation of values already available in plots, tables, labels, and the mapping legend. No task, finding, or progression decision requires hearing it.",
});

const MIN_TONE_GAIN = 0.018;
const MIN_TONE_DURATION = 0.025;
const DEFAULT_DURATION_SECONDS = 8;

interface SonificationDraft {
  title: string;
  events: ScienceSonificationEvent[];
  legends: ScienceSonificationLegend[];
  unavailableReason?: string;
}

interface EventInput {
  id: string;
  status: ScienceSonificationDatumStatus;
  startSeconds: number;
  durationSeconds: number;
  frequencyHz: number | null;
  gain: number;
  waveform: ScienceSonificationWaveform | null;
  sourceSeries: string;
  sourceIndex: number | null;
  sourceValue: number | null;
  sourceValueUnit: string;
  sourcePosition?: ScienceSonificationCoordinate[];
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function round(value: number): number {
  return Number(value.toFixed(6));
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function finiteValues(values: readonly unknown[]): number[] {
  return values.filter(finite);
}

function numericRange(values: readonly unknown[]): ScienceSonificationRange | null {
  const usable = finiteValues(values);
  if (usable.length === 0) return null;
  return {
    minimum: Math.min(...usable),
    maximum: Math.max(...usable),
  };
}

function normalized(
  value: number,
  domain: ScienceSonificationRange,
): number {
  const width = domain.maximum - domain.minimum;
  return width === 0
    ? 0.5
    : clamp((value - domain.minimum) / width, 0, 1);
}

function normalizedMagnitude(value: number, maximumMagnitude: number): number {
  return maximumMagnitude <= 0
    ? 0
    : clamp(Math.abs(value) / maximumMagnitude, 0, 1);
}

function mapRange(
  unitValue: number,
  output: ScienceSonificationRange,
): number {
  return output.minimum + clamp(unitValue, 0, 1) *
    (output.maximum - output.minimum);
}

function statusForValue(value: unknown): ScienceSonificationDatumStatus {
  if (!finite(value)) return "missing";
  return value === 0 ? "zero" : "observed";
}

function sourceStatus(
  values: readonly unknown[],
  explicitlyWithheld = false,
): ScienceSonificationSourceStatus {
  if (explicitlyWithheld) return "withheld";
  if (values.length === 0) return "missing";
  const available = values.filter(finite).length;
  if (available === 0) return "missing";
  return available === values.length ? "available" : "partial";
}

function sampledIndexes(length: number, requested: number): number[] {
  const count = Math.min(length, Math.max(0, Math.floor(requested)));
  if (count === 0) return [];
  if (count === 1) return [0];
  return Array.from(
    { length: count },
    (_, index) => Math.round((index * (length - 1)) / (count - 1)),
  );
}

function metricNumber(
  frame: FacilityScienceFrame,
  label: string,
): number | null {
  const metric = frame.metrics.find((candidate) => candidate.label === label);
  if (!metric) return null;
  const match = metric.value.match(/-?(?:\d+(?:\.\d+)?|\.\d+)/u);
  if (!match) return null;
  const parsed = Number(match[0]);
  return Number.isFinite(parsed) ? parsed : null;
}

function retainedRecord(
  frame: FacilityScienceFrame,
  channel: string,
): boolean | null {
  return frame.records.find((record) => record.channel === channel)?.retained ??
    null;
}

function event(input: EventInput): ScienceSonificationEvent {
  const silent = input.status === "missing" || input.status === "withheld";
  return {
    id: input.id,
    kind: silent ? "silence" : "tone",
    status: input.status,
    startSeconds: round(Math.max(0, input.startSeconds)),
    durationSeconds: round(Math.max(MIN_TONE_DURATION, input.durationSeconds)),
    frequencyHz:
      silent || input.frequencyHz === null
        ? null
        : round(
            clamp(
              input.frequencyHz,
              SCIENCE_SONIFICATION_LIMITS.minimumFrequencyHz,
              SCIENCE_SONIFICATION_LIMITS.maximumFrequencyHz,
            ),
          ),
    gain:
      silent
        ? 0
        : round(
            clamp(
              input.gain,
              0,
              SCIENCE_SONIFICATION_LIMITS.maximumGain,
            ),
          ),
    waveform: silent ? null : input.waveform,
    sourceSeries: input.sourceSeries,
    sourceIndex: input.sourceIndex,
    sourceValue: finite(input.sourceValue) ? input.sourceValue : null,
    sourceValueUnit: input.sourceValueUnit,
    sourcePosition: input.sourcePosition ?? [],
  };
}

function makeLegend(
  input: Omit<
    ScienceSonificationLegend,
    "outputPitchHz" | "outputTimeSeconds" | "outputGain"
  > & {
    outputPitchHz?: ScienceSonificationRange;
    outputTimeSeconds?: ScienceSonificationRange;
    outputGain?: ScienceSonificationRange;
  },
): ScienceSonificationLegend {
  return {
    ...input,
    outputPitchHz: input.outputPitchHz ?? {
      minimum: SCIENCE_SONIFICATION_LIMITS.minimumFrequencyHz,
      maximum: SCIENCE_SONIFICATION_LIMITS.maximumFrequencyHz,
    },
    outputTimeSeconds: input.outputTimeSeconds ?? {
      minimum: 0,
      maximum: DEFAULT_DURATION_SECONDS,
    },
    outputGain: input.outputGain ?? {
      minimum: 0,
      maximum: SCIENCE_SONIFICATION_LIMITS.maximumGain,
    },
  };
}

function unavailableDraft(
  title: string,
  reason: string,
  legends: ScienceSonificationLegend[] = [],
): SonificationDraft {
  return { title, events: [], legends, unavailableReason: reason };
}

function boundaryOscilloscope(
  frame: FacilityScienceFrame,
  durationSeconds: number,
  maxEvents: number,
): SonificationDraft {
  const optical = frame.series.optical ?? [];
  const radio = frame.series.radio ?? [];
  const radioWithheld =
    retainedRecord(frame, "Radio return") === false && radio.length === 0;
  const opticalMissing = optical.length === 0;
  const radioMissing = !radioWithheld && radio.length === 0;
  const availableSeries = [
    ...(opticalMissing
      ? []
      : [{ key: "series.optical", values: optical, waveform: "sine" as const }]),
    ...(radioWithheld || radio.length === 0
      ? []
      : [{ key: "series.radio", values: radio, waveform: "triangle" as const }]),
  ];
  const markerCount =
    Number(opticalMissing) + Number(radioWithheld || radioMissing);
  const samplesPerSeries = Math.max(
    1,
    Math.floor((maxEvents - markerCount) / Math.max(1, availableSeries.length)),
  );
  const allValues = finiteValues([...optical, ...radio]);
  const maximumMagnitude = Math.max(
    0,
    ...allValues.map((value) => Math.abs(value)),
  );
  const pitchRange = { minimum: 220, maximum: 990 };
  const sampleRate = (metricNumber(frame, "Nyquist frequency") ?? 32) * 2;
  const sourceDuration =
    optical.length > 0 ? optical.length / Math.max(1, sampleRate) : 0;
  const compressionRatio =
    sourceDuration > 0 ? sourceDuration / durationSeconds : null;
  const events: ScienceSonificationEvent[] = [];

  for (const source of availableSeries) {
    const indexes = sampledIndexes(source.values.length, samplesPerSeries);
    const step = durationSeconds / Math.max(1, indexes.length);
    for (let eventIndex = 0; eventIndex < indexes.length; eventIndex += 1) {
      const sourceIndex = indexes[eventIndex];
      const value = source.values[sourceIndex];
      const status = statusForValue(value);
      const signedUnit =
        finite(value) && maximumMagnitude > 0
          ? clamp((value / maximumMagnitude + 1) / 2, 0, 1)
          : 0.5;
      events.push(
        event({
          id: `${source.key}-${sourceIndex}`,
          status,
          startSeconds: eventIndex * step,
          durationSeconds: Math.min(0.075, step * 0.86),
          frequencyHz: mapRange(signedUnit, pitchRange),
          gain:
            status === "zero"
              ? MIN_TONE_GAIN
              : mapRange(
                  normalizedMagnitude(finite(value) ? value : 0, maximumMagnitude),
                  { minimum: 0.025, maximum: 0.14 },
                ),
          waveform: source.waveform,
          sourceSeries: source.key,
          sourceIndex,
          sourceValue: finite(value) ? value : null,
          sourceValueUnit: "relative amplitude",
          sourcePosition: [
            {
              label: "Time",
              value: sourceIndex / Math.max(1, sampleRate),
              unit: "s",
            },
          ],
        }),
      );
    }
  }

  if (opticalMissing) {
    events.push(
      event({
        id: "series.optical-missing",
        status: "missing",
        startSeconds: 0,
        durationSeconds,
        frequencyHz: null,
        gain: 0,
        waveform: null,
        sourceSeries: "series.optical",
        sourceIndex: null,
        sourceValue: null,
        sourceValueUnit: "relative amplitude",
      }),
    );
  }

  if (radioWithheld || radioMissing) {
    events.push(
      event({
        id: `series.radio-${radioWithheld ? "withheld" : "missing"}`,
        status: radioWithheld ? "withheld" : "missing",
        startSeconds: 0,
        durationSeconds,
        frequencyHz: null,
        gain: 0,
        waveform: null,
        sourceSeries: "series.radio",
        sourceIndex: null,
        sourceValue: null,
        sourceValueUnit: "relative amplitude",
      }),
    );
  }

  const commonMapping = {
    sourceUnit: "relative amplitude",
    outputPitchHz: pitchRange,
    outputTimeSeconds: { minimum: 0, maximum: durationSeconds },
    outputGain: { minimum: 0, maximum: 0.14 },
    scale: "linear" as const,
    pitchMapping:
      "Signed amplitude maps linearly to pitch; negative values are lower and positive values are higher.",
    timeMapping:
      "Original sample order maps to schedule time. Selected events use original samples only.",
    gainMapping:
      "Absolute amplitude maps to gain with a low audible reference for an exact zero.",
    normalization:
      "Optical and radio channels share the maximum absolute finite amplitude so their relative levels remain comparable.",
    timeCompressionRatio: compressionRatio,
    timeCompression:
      compressionRatio === null
        ? "Source time scale is unavailable."
        : `${compressionRatio.toFixed(3)}x source-time/schedule-time; ${
            compressionRatio < 1 ? "the source is expanded" : "the source is compressed"
          }.`,
  };
  const legends = [
    makeLegend({
      id: "boundary-optical-waveform",
      label: "Optical waveform",
      sourceSeries: "series.optical",
      sourceStatus: sourceStatus(optical),
      sourceDomain: numericRange(optical),
      plainLanguage: opticalMissing
        ? "The optical waveform is missing, so its full lane remains a labeled silent gap and no waveform is inferred."
        : "Each retained optical sample becomes a short sine tone. Time is left-to-right, pitch is signed amplitude, and loudness is amplitude magnitude.",
      ...commonMapping,
    }),
    makeLegend({
      id: "boundary-radio-waveform",
      label: "Radio waveform",
      sourceSeries: "series.radio",
      sourceStatus: sourceStatus(radio, radioWithheld),
      sourceDomain: numericRange(radio),
      plainLanguage: radioWithheld
        ? "The radio return is withheld, so its full lane remains a labeled silent gap and no waveform is inferred."
        : radioMissing
          ? "The radio return is missing, so its full lane remains a labeled silent gap and no waveform is inferred."
          : "Each retained radio sample becomes a short triangle tone using the same time, pitch, and loudness scale as the optical channel.",
      ...commonMapping,
    }),
  ];

  return events.some((candidate) => candidate.kind === "tone")
    ? { title: "Boundary waveform sonification", events, legends }
    : unavailableDraft(
        "Boundary waveform sonification",
        "No finite waveform samples are available.",
        legends,
      );
}

function boundarySpectrum(
  frame: FacilityScienceFrame,
  durationSeconds: number,
  maxEvents: number,
): SonificationDraft {
  const values = frame.series.spectrum ?? [];
  const indexes = sampledIndexes(values.length, maxEvents);
  const sourceDomain = numericRange(values);
  const nyquist = metricNumber(frame, "Nyquist frequency") ?? 32;
  const sampleRate = nyquist * 2;
  const frequencyAt = (index: number) =>
    values.length > 0 ? (index * sampleRate) / 128 : 0;
  const maximumSourceFrequency =
    values.length > 0 ? frequencyAt(values.length - 1) : 0;
  const pitchRange = { minimum: 160, maximum: 1_400 };
  const maximumAmplitude = Math.max(0, ...finiteValues(values));
  const step = durationSeconds / Math.max(1, indexes.length);
  const events = indexes.map((sourceIndex, eventIndex) => {
    const value = values[sourceIndex];
    const status = statusForValue(value);
    const sourceFrequency = frequencyAt(sourceIndex);
    return event({
      id: `series.spectrum-${sourceIndex}`,
      status,
      startSeconds: eventIndex * step,
      durationSeconds: Math.min(0.12, step * 0.82),
      frequencyHz: mapRange(
        maximumSourceFrequency > 0
          ? sourceFrequency / maximumSourceFrequency
          : 0,
        pitchRange,
      ),
      gain:
        status === "zero"
          ? MIN_TONE_GAIN
          : mapRange(
              maximumAmplitude > 0 && finite(value)
                ? value / maximumAmplitude
                : 0,
              { minimum: 0.025, maximum: 0.16 },
            ),
      waveform: "sine",
      sourceSeries: "series.spectrum",
      sourceIndex,
      sourceValue: finite(value) ? value : null,
      sourceValueUnit: "relative spectral amplitude",
      sourcePosition: [
        { label: "Source frequency", value: sourceFrequency, unit: "Hz" },
      ],
    });
  });
  const legends = [
    makeLegend({
      id: "boundary-spectrum",
      label: "Filtered spectrum",
      sourceSeries: "series.spectrum",
      sourceStatus: sourceStatus(values),
      sourceUnit: "relative spectral amplitude",
      sourceDomain,
      outputPitchHz: pitchRange,
      outputTimeSeconds: { minimum: 0, maximum: durationSeconds },
      outputGain: { minimum: 0, maximum: 0.16 },
      scale: "linear",
      pitchMapping:
        "Analysis-bin frequency maps linearly from low to high audible pitch.",
      timeMapping:
        "Frequency bins scan in ascending order; sampled bins are existing bins and are not interpolated.",
      gainMapping:
        "Spectral amplitude maps linearly to gain; an exact zero uses the quiet reference tone.",
      normalization:
        "Gain is normalized to the largest finite amplitude in the displayed spectrum.",
      timeCompressionRatio: null,
      timeCompression:
        "Not applicable: this is a frequency-bin scan, not time-domain playback.",
      plainLanguage:
        "The scan rises in pitch with analysis frequency. Louder tones mark stronger displayed spectral components.",
    }),
  ];
  return events.some((candidate) => candidate.kind === "tone")
    ? { title: "Boundary spectrum sonification", events, legends }
    : unavailableDraft(
        "Boundary spectrum sonification",
        "No finite spectral bins are available.",
        legends,
      );
}

function boundaryCorrelation(
  frame: FacilityScienceFrame,
  durationSeconds: number,
  maxEvents: number,
): SonificationDraft {
  const lag = frame.series.lag ?? [];
  const residual = frame.series.residual ?? [];
  const radioWithheld = retainedRecord(frame, "Radio return") === false;
  const lagSegment = durationSeconds * 0.42;
  const residualSegment = durationSeconds - lagSegment;
  const lagBudget = Math.min(lag.length, Math.max(1, Math.floor(maxEvents * 0.3)));
  const residualBudget = Math.max(1, maxEvents - lagBudget);
  const lagIndexes = sampledIndexes(lag.length, lagBudget);
  const residualIndexes = sampledIndexes(residual.length, residualBudget);
  const sampleRate = (metricNumber(frame, "Nyquist frequency") ?? 32) * 2;
  const residualRange = numericRange(residual);
  const residualMaximum = Math.max(
    0,
    ...finiteValues(residual).map((value) => Math.abs(value)),
  );
  const events: ScienceSonificationEvent[] = [];

  if (lag.length === 0 && radioWithheld) {
    events.push(
      event({
        id: "series.lag-withheld",
        status: "withheld",
        startSeconds: 0,
        durationSeconds: lagSegment,
        frequencyHz: null,
        gain: 0,
        waveform: null,
        sourceSeries: "series.lag",
        sourceIndex: null,
        sourceValue: null,
        sourceValueUnit: "correlation coefficient",
      }),
    );
  } else {
    const step = lagSegment / Math.max(1, lagIndexes.length);
    lagIndexes.forEach((sourceIndex, eventIndex) => {
      const value = lag[sourceIndex];
      const status = statusForValue(value);
      const lagSamples = sourceIndex - Math.floor(lag.length / 2);
      events.push(
        event({
          id: `series.lag-${sourceIndex}`,
          status,
          startSeconds: eventIndex * step,
          durationSeconds: Math.min(0.11, step * 0.8),
          frequencyHz: mapRange(
            finite(value) ? clamp((value + 1) / 2, 0, 1) : 0.5,
            { minimum: 220, maximum: 880 },
          ),
          gain:
            status === "zero"
              ? MIN_TONE_GAIN
              : mapRange(finite(value) ? Math.abs(value) : 0, {
                  minimum: 0.025,
                  maximum: 0.15,
                }),
          waveform: "sine",
          sourceSeries: "series.lag",
          sourceIndex,
          sourceValue: finite(value) ? value : null,
          sourceValueUnit: "correlation coefficient",
          sourcePosition: [
            {
              label: "Trial lag",
              value: (lagSamples / Math.max(1, sampleRate)) * 1_000,
              unit: "ms",
            },
          ],
        }),
      );
    });
  }

  if (residual.length === 0 && radioWithheld) {
    events.push(
      event({
        id: "series.residual-withheld",
        status: "withheld",
        startSeconds: lagSegment,
        durationSeconds: residualSegment,
        frequencyHz: null,
        gain: 0,
        waveform: null,
        sourceSeries: "series.residual",
        sourceIndex: null,
        sourceValue: null,
        sourceValueUnit: "mV",
      }),
    );
  } else {
    const step = residualSegment / Math.max(1, residualIndexes.length);
    residualIndexes.forEach((sourceIndex, eventIndex) => {
      const value = residual[sourceIndex];
      const status = statusForValue(value);
      const signedUnit =
        finite(value) && residualMaximum > 0
          ? clamp((value / residualMaximum + 1) / 2, 0, 1)
          : 0.5;
      events.push(
        event({
          id: `series.residual-${sourceIndex}`,
          status,
          startSeconds: lagSegment + eventIndex * step,
          durationSeconds: Math.min(0.075, step * 0.84),
          frequencyHz: mapRange(signedUnit, {
            minimum: 180,
            maximum: 1_080,
          }),
          gain:
            status === "zero"
              ? MIN_TONE_GAIN
              : mapRange(
                  normalizedMagnitude(
                    finite(value) ? value : 0,
                    residualMaximum,
                  ),
                  { minimum: 0.025, maximum: 0.14 },
                ),
          waveform: "triangle",
          sourceSeries: "series.residual",
          sourceIndex,
          sourceValue: finite(value) ? value * 1_000 : null,
          sourceValueUnit: "mV",
          sourcePosition: [
            {
              label: "Sample time",
              value: sourceIndex / Math.max(1, sampleRate),
              unit: "s",
            },
          ],
        }),
      );
    });
  }

  const legends = [
    makeLegend({
      id: "boundary-lag-scan",
      label: "Lag correlation",
      sourceSeries: "series.lag",
      sourceStatus: sourceStatus(lag, radioWithheld && lag.length === 0),
      sourceUnit: "correlation coefficient",
      sourceDomain: numericRange(lag),
      outputPitchHz: { minimum: 220, maximum: 880 },
      outputTimeSeconds: { minimum: 0, maximum: lagSegment },
      outputGain: { minimum: 0, maximum: 0.15 },
      scale: "linear",
      pitchMapping:
        "Correlation from -1 to +1 maps linearly to pitch.",
      timeMapping:
        "Trial lags scan from negative to positive using the existing lag bins.",
      gainMapping:
        "Absolute correlation maps to gain; zero is the quiet reference tone.",
      normalization:
        "The fixed physical coefficient domain [-1, +1] is used; values are not normalized to the local peak.",
      timeCompressionRatio: null,
      timeCompression:
        "Not applicable: trial lag is an analysis axis rather than elapsed playback time.",
      plainLanguage:
        radioWithheld && lag.length === 0
          ? "Lag cannot be calculated while the radio return is withheld, so this section remains a labeled silent gap."
          : "The first section scans possible time offsets. Higher pitch means stronger positive correlation; loudness means larger correlation magnitude.",
    }),
    makeLegend({
      id: "boundary-residual",
      label: "Optical-radio residual",
      sourceSeries: "series.residual",
      sourceStatus: sourceStatus(
        residual,
        radioWithheld && residual.length === 0,
      ),
      sourceUnit: "mV",
      sourceDomain:
        residualRange === null
          ? null
          : {
              minimum: residualRange.minimum * 1_000,
              maximum: residualRange.maximum * 1_000,
            },
      outputPitchHz: { minimum: 180, maximum: 1_080 },
      outputTimeSeconds: {
        minimum: lagSegment,
        maximum: durationSeconds,
      },
      outputGain: { minimum: 0, maximum: 0.14 },
      scale: "linear",
      pitchMapping:
        "Signed residual maps linearly around a central pitch.",
      timeMapping:
        "Residual samples retain sample order and occupy the second schedule section.",
      gainMapping:
        "Absolute residual magnitude maps to gain; zero is the quiet reference tone.",
      normalization:
        "Pitch and gain share the maximum absolute finite residual; no missing value is interpolated.",
      timeCompressionRatio:
        residual.length > 0
          ? residual.length / Math.max(1, sampleRate) / residualSegment
          : null,
      timeCompression:
        residual.length > 0
          ? "The displayed residual time span is mapped into the second schedule section."
          : "Source time scale is unavailable.",
      plainLanguage:
        radioWithheld && residual.length === 0
          ? "Residuals require both channels. With the radio return withheld, this section remains a labeled silent gap."
          : "The second section follows residual sample order. Pitch shows sign and loudness shows error magnitude.",
    }),
  ];
  return events.some((candidate) => candidate.kind === "tone")
    ? { title: "Boundary lag and residual sonification", events, legends }
    : unavailableDraft(
        "Boundary lag and residual sonification",
        radioWithheld
          ? "The radio return is withheld; lag and residual products require both channels."
          : "No finite lag or residual samples are available.",
        legends,
      );
}

function subsurfaceDepthFrequency(
  frame: FacilityScienceFrame,
  durationSeconds: number,
  maxEvents: number,
): SonificationDraft {
  const matrix = frame.matrix ?? [];
  const depthResponse = frame.series.depthResponse ?? [];
  const maximumDepth = metricNumber(frame, "Modeled depth span") ?? 18;
  const matrixSegment = durationSeconds * 0.72;
  const responseSegment = durationSeconds - matrixSegment;
  const responseBudget = Math.min(
    depthResponse.length,
    Math.max(1, Math.floor(maxEvents * 0.2)),
  );
  const matrixBudget = Math.max(1, maxEvents - responseBudget);
  const rowCount = matrix.length;
  const columnCount = Math.max(0, ...matrix.map((row) => row.length));
  const sampledRowCount =
    rowCount === 0 || columnCount === 0
      ? 0
      : Math.min(
          rowCount,
          Math.max(
            1,
            Math.floor(Math.sqrt((matrixBudget * rowCount) / columnCount)),
          ),
        );
  const sampledColumnCount =
    sampledRowCount === 0
      ? 0
      : Math.min(columnCount, Math.floor(matrixBudget / sampledRowCount));
  const rowIndexes = sampledIndexes(rowCount, sampledRowCount);
  const columnIndexes = sampledIndexes(columnCount, sampledColumnCount);
  const fieldValues = matrix.flatMap((row) => finiteValues(row));
  const fieldMaximum = Math.max(0, ...fieldValues);
  const pitchRange = { minimum: 180, maximum: 1_260 };
  const events: ScienceSonificationEvent[] = [];
  const totalFieldEvents = Math.max(1, rowIndexes.length * columnIndexes.length);
  let fieldEventIndex = 0;

  for (const rowIndex of rowIndexes) {
    for (const columnIndex of columnIndexes) {
      const value = matrix[rowIndex]?.[columnIndex];
      const status = statusForValue(value);
      const sourceFrequency =
        columnCount <= 1 ? 1 : 1 + (columnIndex / (columnCount - 1)) * 23;
      const sourceDepth =
        rowCount <= 1
          ? 0.5
          : 0.5 + (rowIndex / (rowCount - 1)) * (maximumDepth - 0.5);
      const step = matrixSegment / totalFieldEvents;
      events.push(
        event({
          id: `matrix-${rowIndex}-${columnIndex}`,
          status,
          startSeconds: fieldEventIndex * step,
          durationSeconds: Math.min(0.09, step * 0.82),
          frequencyHz: mapRange((sourceFrequency - 1) / 23, pitchRange),
          gain:
            status === "zero"
              ? MIN_TONE_GAIN
              : mapRange(
                  fieldMaximum > 0 && finite(value)
                    ? value / fieldMaximum
                    : 0,
                  { minimum: 0.022, maximum: 0.15 },
                ),
          waveform: "sine",
          sourceSeries: "matrix",
          sourceIndex: rowIndex * Math.max(1, columnCount) + columnIndex,
          sourceValue: finite(value) ? value : null,
          sourceValueUnit: "relative modal response",
          sourcePosition: [
            { label: "Depth", value: sourceDepth, unit: "km" },
            { label: "Frequency", value: sourceFrequency, unit: "Hz" },
          ],
        }),
      );
      fieldEventIndex += 1;
    }
  }

  const responseIndexes = sampledIndexes(depthResponse.length, responseBudget);
  const responseMaximum = Math.max(0, ...finiteValues(depthResponse));
  const responseStep =
    responseSegment / Math.max(1, responseIndexes.length);
  responseIndexes.forEach((sourceIndex, index) => {
    const value = depthResponse[sourceIndex];
    const status = statusForValue(value);
    const sourceDepth =
      depthResponse.length <= 1
        ? 0.5
        : 0.5 +
          (sourceIndex / (depthResponse.length - 1)) *
            (maximumDepth - 0.5);
    events.push(
      event({
        id: `series.depthResponse-${sourceIndex}`,
        status,
        startSeconds: matrixSegment + index * responseStep,
        durationSeconds: Math.min(0.12, responseStep * 0.84),
        frequencyHz: mapRange(
          maximumDepth <= 0.5
            ? 0
            : (sourceDepth - 0.5) / (maximumDepth - 0.5),
          { minimum: 160, maximum: 1_000 },
        ),
        gain:
          status === "zero"
            ? MIN_TONE_GAIN
            : mapRange(
                responseMaximum > 0 && finite(value)
                  ? value / responseMaximum
                  : 0,
                { minimum: 0.025, maximum: 0.16 },
              ),
        waveform: "triangle",
        sourceSeries: "series.depthResponse",
        sourceIndex,
        sourceValue: finite(value) ? value : null,
        sourceValueUnit: "relative modal response",
        sourcePosition: [
          { label: "Depth", value: sourceDepth, unit: "km" },
        ],
      }),
    );
  });

  const legends = [
    makeLegend({
      id: "subsurface-depth-frequency-field",
      label: "Depth-frequency field",
      sourceSeries: "matrix",
      sourceStatus: sourceStatus(matrix.flat()),
      sourceUnit: "relative modal response",
      sourceDomain: numericRange(matrix.flat()),
      outputPitchHz: pitchRange,
      outputTimeSeconds: { minimum: 0, maximum: matrixSegment },
      outputGain: { minimum: 0, maximum: 0.15 },
      scale: "linear",
      pitchMapping:
        "Mode frequency from 1 to 24 Hz maps linearly to audible pitch.",
      timeMapping:
        "Selected existing cells scan by depth, then frequency. No cell is interpolated.",
      gainMapping:
        "Modal response maps linearly to gain; an exact zero uses the quiet reference tone.",
      normalization:
        "Gain is normalized to the maximum finite response in the full displayed matrix, including cells omitted only for event-count control.",
      timeCompressionRatio: null,
      timeCompression:
        "Not applicable: depth and frequency are analysis axes rather than elapsed playback time.",
      plainLanguage:
        "The first section scans retained depth-frequency cells. Pitch is frequency, loudness is response strength, and depth advances through schedule time.",
    }),
    makeLegend({
      id: "subsurface-depth-response",
      label: "Trial-frequency depth response",
      sourceSeries: "series.depthResponse",
      sourceStatus: sourceStatus(depthResponse),
      sourceUnit: "relative modal response",
      sourceDomain: numericRange(depthResponse),
      outputPitchHz: { minimum: 160, maximum: 1_000 },
      outputTimeSeconds: {
        minimum: matrixSegment,
        maximum: durationSeconds,
      },
      outputGain: { minimum: 0, maximum: 0.16 },
      scale: "linear",
      pitchMapping: "Modeled depth maps linearly to audible pitch.",
      timeMapping:
        "Existing depth-response samples scan from shallow to deep in the second section.",
      gainMapping:
        "Response maps linearly to gain; an exact zero uses the quiet reference tone.",
      normalization:
        "Gain is normalized to the largest finite displayed depth response. The sonifier does not generate intermediate samples.",
      timeCompressionRatio: null,
      timeCompression:
        "Not applicable: modeled depth is an analysis axis rather than elapsed playback time.",
      plainLanguage:
        "The second section rises in pitch with modeled depth. Louder tones mark a stronger response at the selected trial frequency.",
    }),
  ];
  return events.some((candidate) => candidate.kind === "tone")
    ? { title: "Subsurface depth and frequency sonification", events, legends }
    : unavailableDraft(
        "Subsurface depth and frequency sonification",
        "No finite depth-frequency or depth-response values are available.",
        legends,
      );
}

function subsurfaceSpectrum(
  frame: FacilityScienceFrame,
  durationSeconds: number,
  maxEvents: number,
): SonificationDraft {
  const values = frame.series.spectrum ?? [];
  const indexes = sampledIndexes(values.length, maxEvents);
  const maximumResponse = Math.max(0, ...finiteValues(values));
  const pitchRange = { minimum: 180, maximum: 1_260 };
  const step = durationSeconds / Math.max(1, indexes.length);
  const events = indexes.map((sourceIndex, eventIndex) => {
    const value = values[sourceIndex];
    const status = statusForValue(value);
    const sourceFrequency =
      values.length <= 1
        ? 1
        : 1 + (sourceIndex / (values.length - 1)) * 23;
    return event({
      id: `series.spectrum-${sourceIndex}`,
      status,
      startSeconds: eventIndex * step,
      durationSeconds: Math.min(0.14, step * 0.82),
      frequencyHz: mapRange((sourceFrequency - 1) / 23, pitchRange),
      gain:
        status === "zero"
          ? MIN_TONE_GAIN
          : mapRange(
              maximumResponse > 0 && finite(value)
                ? value / maximumResponse
                : 0,
              { minimum: 0.025, maximum: 0.16 },
            ),
      waveform: "sine",
      sourceSeries: "series.spectrum",
      sourceIndex,
      sourceValue: finite(value) ? value : null,
      sourceValueUnit: "relative modal response",
      sourcePosition: [
        { label: "Mode frequency", value: sourceFrequency, unit: "Hz" },
      ],
    });
  });
  const legends = [
    makeLegend({
      id: "subsurface-mode-spectrum",
      label: "Mode spectrum",
      sourceSeries: "series.spectrum",
      sourceStatus: sourceStatus(values),
      sourceUnit: "relative modal response",
      sourceDomain: numericRange(values),
      outputPitchHz: pitchRange,
      outputTimeSeconds: { minimum: 0, maximum: durationSeconds },
      outputGain: { minimum: 0, maximum: 0.16 },
      scale: "linear",
      pitchMapping:
        "Source mode frequency from 1 to 24 Hz maps linearly to audible pitch.",
      timeMapping:
        "Existing frequency bins scan from low to high without interpolation.",
      gainMapping:
        "Modal response maps linearly to gain; an exact zero uses the quiet reference tone.",
      normalization:
        "Gain is normalized to the largest finite response in the displayed spectrum.",
      timeCompressionRatio: null,
      timeCompression:
        "Not applicable: this is a frequency-bin scan, not time-domain playback.",
      plainLanguage:
        "Pitch and scan order both rise with mode frequency. Louder tones mark stronger modal response.",
    }),
  ];
  return events.some((candidate) => candidate.kind === "tone")
    ? { title: "Subsurface mode-spectrum sonification", events, legends }
    : unavailableDraft(
        "Subsurface mode-spectrum sonification",
        "No finite mode-spectrum bins are available.",
        legends,
      );
}

function subsurfaceStations(
  frame: FacilityScienceFrame,
  durationSeconds: number,
): SonificationDraft {
  const retainedValues = frame.series.stations ?? [];
  const records = frame.records.filter((record) =>
    /^Station \d+$/u.test(record.channel)
  );
  const stationCount = Math.max(records.length, retainedValues.length);
  let retainedIndex = 0;
  const stationSlots = Array.from({ length: stationCount }, (_, index) => {
    const record = records[index];
    if (record?.retained === false) {
      return { index, status: "withheld" as const, value: null };
    }
    const value = retainedValues[retainedIndex];
    retainedIndex += 1;
    return {
      index,
      status: statusForValue(value),
      value: finite(value) ? value : null,
    };
  });
  const finiteStations = stationSlots
    .map((station) => station.value)
    .filter(finite);
  const stationMaximum = Math.max(0, ...finiteStations);
  const step = durationSeconds / Math.max(1, stationSlots.length);
  const events = stationSlots.map((station, eventIndex) =>
    event({
      id: `series.stations-${station.index}`,
      status: station.status,
      startSeconds: eventIndex * step,
      durationSeconds: Math.min(0.45, step * 0.72),
      frequencyHz: mapRange(
        stationCount <= 1 ? 0 : station.index / (stationCount - 1),
        { minimum: 220, maximum: 660 },
      ),
      gain:
        station.status === "zero"
          ? MIN_TONE_GAIN
          : mapRange(
              stationMaximum > 0 && station.value !== null
                ? station.value / stationMaximum
                : 0,
              { minimum: 0.03, maximum: 0.16 },
            ),
      waveform: "triangle",
      sourceSeries: "series.stations",
      sourceIndex: station.index,
      sourceValue: station.value,
      sourceValueUnit: "coherence coefficient",
      sourcePosition: [
        { label: "Station", value: station.index + 1, unit: "index" },
      ],
    })
  );
  const withheldLabels = stationSlots
    .filter((station) => station.status === "withheld")
    .map((station) => `Station ${String(station.index + 1).padStart(2, "0")}`);
  const missingLabels = stationSlots
    .filter((station) => station.status === "missing")
    .map((station) => `Station ${String(station.index + 1).padStart(2, "0")}`);
  const sourceStatusValue: ScienceSonificationSourceStatus =
    withheldLabels.length > 0 || missingLabels.length > 0
      ? finiteStations.length > 0
        ? "partial"
        : withheldLabels.length > 0
          ? "withheld"
          : "missing"
      : finiteStations.length > 0
        ? "available"
        : "missing";
  const statusDescription = [
    withheldLabels.length > 0
      ? `${withheldLabels.join(", ")} ${
          withheldLabels.length === 1 ? "is" : "are"
        } withheld.`
      : "",
    missingLabels.length > 0
      ? `${missingLabels.join(", ")} ${
          missingLabels.length === 1 ? "is" : "are"
        } missing.`
      : "",
  ].filter(Boolean).join(" ");
  const legends = [
    makeLegend({
      id: "subsurface-station-coherence",
      label: "Station coherence",
      sourceSeries: "series.stations",
      sourceStatus: sourceStatusValue,
      sourceUnit: "coherence coefficient",
      sourceDomain: numericRange(finiteStations),
      outputPitchHz: { minimum: 220, maximum: 660 },
      outputTimeSeconds: { minimum: 0, maximum: durationSeconds },
      outputGain: { minimum: 0, maximum: 0.16 },
      scale: "linear",
      pitchMapping:
        "Station order maps linearly to pitch; pitch does not represent geography.",
      timeMapping:
        "Stations scan in numbered order with one schedule slot per station.",
      gainMapping:
        "Retained coherence maps linearly to gain; exact zero uses the quiet reference tone.",
      normalization:
        "Gain is normalized to the largest finite retained station value. Missing and withheld stations remain silent slots.",
      timeCompressionRatio: null,
      timeCompression:
        "Not applicable: station order is not elapsed playback time.",
      plainLanguage: `Each numbered station has a fixed place in the scan. Loudness represents retained coherence. ${
        statusDescription || "All listed stations have retained values."
      }`,
    }),
  ];
  return events.some((candidate) => candidate.kind === "tone")
    ? { title: "Subsurface station-coherence sonification", events, legends }
    : unavailableDraft(
        "Subsurface station-coherence sonification",
        withheldLabels.length > 0
          ? "All station values are withheld."
          : "No finite station-coherence values are available.",
        legends,
      );
}

function buildDraft(
  facilityId: EnvironmentalFacilityId,
  toolId: string,
  frame: FacilityScienceFrame,
  durationSeconds: number,
  maxEvents: number,
): SonificationDraft {
  if (facilityId === "boundary_array") {
    switch (toolId) {
      case "oscilloscope":
        return boundaryOscilloscope(frame, durationSeconds, maxEvents);
      case "spectrum":
        return boundarySpectrum(frame, durationSeconds, maxEvents);
      case "correlation":
        return boundaryCorrelation(frame, durationSeconds, maxEvents);
      default:
        return unavailableDraft(
          "Boundary sonification",
          `No sonification mapping is defined for the ${toolId || "selected"} tool.`,
        );
    }
  }
  if (facilityId === "subsurface_resonance_station") {
    switch (toolId) {
      case "depthFrequency":
        return subsurfaceDepthFrequency(frame, durationSeconds, maxEvents);
      case "spectrum":
        return subsurfaceSpectrum(frame, durationSeconds, maxEvents);
      case "stations":
        return subsurfaceStations(frame, durationSeconds);
      default:
        return unavailableDraft(
          "Subsurface sonification",
          `No sonification mapping is defined for the ${toolId || "selected"} tool.`,
        );
    }
  }
  return unavailableDraft(
    "Scientific sonification",
    "Sonification is not yet mapped for this workstation.",
  );
}

export function isScienceSonificationSupported(
  facilityId: EnvironmentalFacilityId,
  toolId: string,
): boolean {
  if (facilityId === "boundary_array") {
    return (
      SUPPORTED_SCIENCE_SONIFICATION_TOOLS.boundary_array as readonly string[]
    ).includes(toolId);
  }
  if (facilityId === "subsurface_resonance_station") {
    return (
      SUPPORTED_SCIENCE_SONIFICATION_TOOLS.subsurface_resonance_station as readonly string[]
    ).includes(toolId);
  }
  return false;
}

/**
 * Produces deterministic, bounded data-to-audio instructions. This function
 * performs no playback and has no browser or audio-engine dependency.
 */
export function buildScienceSonification(
  facilityId: EnvironmentalFacilityId,
  toolId: string,
  frame: FacilityScienceFrame,
  options: ScienceSonificationOptions = {},
): ScienceSonificationSchedule {
  const durationSeconds = round(
    clamp(
      finite(options.durationSeconds)
        ? options.durationSeconds
        : DEFAULT_DURATION_SECONDS,
      1,
      SCIENCE_SONIFICATION_LIMITS.maximumDurationSeconds,
    ),
  );
  const maxEvents = Math.floor(
    clamp(
      finite(options.maxEvents)
        ? options.maxEvents
        : SCIENCE_SONIFICATION_LIMITS.maximumEvents,
      1,
      SCIENCE_SONIFICATION_LIMITS.maximumEvents,
    ),
  );
  const draft = buildDraft(
    facilityId,
    toolId,
    frame,
    durationSeconds,
    maxEvents,
  );
  const events = draft.events
    .slice(0, maxEvents)
    .map((candidate) => ({
      ...candidate,
      startSeconds: round(
        clamp(candidate.startSeconds, 0, durationSeconds),
      ),
      durationSeconds: round(
        Math.min(
          candidate.durationSeconds,
          Math.max(
            MIN_TONE_DURATION,
            durationSeconds -
              clamp(candidate.startSeconds, 0, durationSeconds),
          ),
        ),
      ),
    }));
  const hasTone = events.some((candidate) => candidate.kind === "tone");
  return {
    status: hasTone ? "available" : "unavailable",
    unavailableReason:
      hasTone
        ? null
        : draft.unavailableReason ?? "No finite source values are available.",
    facilityId,
    toolId,
    title: draft.title,
    durationSeconds,
    events,
    legends: draft.legends,
    statusLegend: SCIENCE_SONIFICATION_STATUS_LEGEND,
    accessibility: ACCESSIBILITY,
  };
}
