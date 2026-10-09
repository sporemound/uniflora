import type { EnvironmentName } from "./public-state";

export interface ActivityWaveformSample {
  sampleIndex: number;
  timeSeconds: number;
  rawVoltageV: number;
  calibratedVoltageV: number;
  uncertaintyV: number;
  residualVoltageV: number;
  quality: string;
}

export interface ActivityEventMarker {
  eventId: string;
  label: string;
  timeSeconds: number;
  source: string;
  uncertaintySeconds: number;
}

export interface ActivityDerivedValue {
  valueId: string;
  label: string;
  value: number;
  unit: string;
  uncertainty: number;
}

export interface ActivityScientificDataset {
  schemaVersion: "3.0.0";
  artifactId: string;
  visualizationId: string;
  environment: EnvironmentName;
  positionId: string;
  institutionId: string;
  title: string;
  stateHeadHash: string;
  artifactDefinitionHash: string;
  inputDatasetHash: string;
  generatedAt: string;
  referenceTimeUtc: string;
  sampleRateHz: number;
  sourceClockId: string;
  timeZones: {
    facility: string;
    source: string;
    named: Record<string, string>;
  };
  waveform: {
    fullSampleCount: number;
    publishedSampleCount: number;
    startSeconds: number;
    endSeconds: number;
    samples: ActivityWaveformSample[];
    qualityIntervals: Array<{
      startSeconds: number;
      endSeconds: number;
      quality: string;
    }>;
  };
  spectrogram: {
    timeSeconds: number[];
    frequencyHz: number[];
    powerDb: number[][];
    minimumDb: number;
    maximumDb: number;
    units: string;
  };
  events: ActivityEventMarker[];
  derivedValues: ActivityDerivedValue[];
  publicSummary: string;
  limitations: string[];
}

export type ActivityWaveformSeriesId =
  | "rawVoltageV"
  | "calibratedVoltageV"
  | "residualVoltageV";

export interface ActivityWaveformSeries {
  id: ActivityWaveformSeriesId;
  label: string;
  unit: string;
  defaultVisible: boolean;
}

export interface ActivityLinkedTimeseriesView {
  id: "waveform";
  type: "linked-timeseries";
  x: "timeSeconds";
  series: [
    ActivityWaveformSeries & { id: "rawVoltageV" },
    ActivityWaveformSeries & { id: "calibratedVoltageV" },
    ActivityWaveformSeries & { id: "residualVoltageV" },
  ];
  uncertaintyField: "uncertaintyV";
  eventField: "events";
}

export interface ActivityLinkedSpectrogramView {
  id: "spectrogram";
  type: "linked-spectrogram";
  x: "timeSeconds";
  y: "frequencyHz";
  value: "powerDb";
  units: string;
}

export interface ActivityVisualizationSpec {
  schemaVersion: "3.0.0";
  visualizationId: string;
  artifactId: string;
  environment: EnvironmentName;
  title: string;
  renderer: "missing-interior-native-svg-canvas";
  datasetFilename: string;
  fallbackFilename: string;
  manifestFilename: string;
  views: [ActivityLinkedTimeseriesView, ActivityLinkedSpectrogramView];
  interaction: {
    linkedTimeWindow: boolean;
    hoverReadout: boolean;
    dragToSelect: boolean;
    resetControl: boolean;
    timeBases: string[];
  };
  provenance: {
    stateHeadHash: string;
    artifactDefinitionHash: string;
    inputDatasetHash: string;
    analysisMethod: string;
    analysisMethodVersion: string;
  };
  limitations: string[];
}

export interface ScientificPublicationSummary {
  environment: EnvironmentName;
  publicationId: string;
  artifactId: string;
  stateHeadHash: string;
  evidenceStateHeadHash: string | null;
  title: string;
  publicSummary: string;
  limitation: string;
  primaryFilename: string;
  manifestFilename: string | null;
  visualizationFilename: string | null;
  dataFilename: string | null;
  publishedAt: string;
}

export interface ScientificBundle {
  delivery: "published" | "bundled-test";
  publication: ScientificPublicationSummary;
  spec: ActivityVisualizationSpec;
  dataset: ActivityScientificDataset;
  fallbackUrl: string | null;
  manifestUrl: string | null;
}

const DATASET_KEYS = [
  "schemaVersion",
  "artifactId",
  "visualizationId",
  "environment",
  "positionId",
  "institutionId",
  "title",
  "stateHeadHash",
  "artifactDefinitionHash",
  "inputDatasetHash",
  "generatedAt",
  "referenceTimeUtc",
  "sampleRateHz",
  "sourceClockId",
  "timeZones",
  "waveform",
  "spectrogram",
  "events",
  "derivedValues",
  "publicSummary",
  "limitations",
] as const;
const TIME_ZONE_KEYS = ["facility", "source", "named"] as const;
const WAVEFORM_KEYS = [
  "fullSampleCount",
  "publishedSampleCount",
  "startSeconds",
  "endSeconds",
  "samples",
  "qualityIntervals",
] as const;
const SAMPLE_KEYS = [
  "sampleIndex",
  "timeSeconds",
  "rawVoltageV",
  "calibratedVoltageV",
  "uncertaintyV",
  "residualVoltageV",
  "quality",
] as const;
const QUALITY_INTERVAL_KEYS = ["startSeconds", "endSeconds", "quality"] as const;
const SPECTROGRAM_KEYS = [
  "timeSeconds",
  "frequencyHz",
  "powerDb",
  "minimumDb",
  "maximumDb",
  "units",
] as const;
const EVENT_KEYS = [
  "eventId",
  "label",
  "timeSeconds",
  "source",
  "uncertaintySeconds",
] as const;
const DERIVED_VALUE_KEYS = ["valueId", "label", "value", "unit", "uncertainty"] as const;
const SPEC_KEYS = [
  "schemaVersion",
  "visualizationId",
  "artifactId",
  "environment",
  "title",
  "renderer",
  "datasetFilename",
  "fallbackFilename",
  "manifestFilename",
  "views",
  "interaction",
  "provenance",
  "limitations",
] as const;
const TIMESERIES_VIEW_KEYS = [
  "id",
  "type",
  "x",
  "series",
  "uncertaintyField",
  "eventField",
] as const;
const SERIES_KEYS = ["id", "label", "unit", "defaultVisible"] as const;
const SPECTROGRAM_VIEW_KEYS = ["id", "type", "x", "y", "value", "units"] as const;
const INTERACTION_KEYS = [
  "linkedTimeWindow",
  "hoverReadout",
  "dragToSelect",
  "resetControl",
  "timeBases",
] as const;
const PROVENANCE_KEYS = [
  "stateHeadHash",
  "artifactDefinitionHash",
  "inputDatasetHash",
  "analysisMethod",
  "analysisMethodVersion",
] as const;
const PUBLICATION_KEYS = [
  "environment",
  "publicationId",
  "artifactId",
  "stateHeadHash",
  "evidenceStateHeadHash",
  "title",
  "publicSummary",
  "limitation",
  "primaryFilename",
  "manifestFilename",
  "visualizationFilename",
  "dataFilename",
  "publishedAt",
] as const;

const IDENTIFIER_PATTERN = /^[a-z0-9][a-z0-9._-]{0,127}$/;
const FILENAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$/;
const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const UTC_TIMESTAMP_PATTERN =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/;

const MAX_LABEL_LENGTH = 512;
const MAX_TEXT_LENGTH = 8_192;
const MAX_TIME_ZONE_LENGTH = 128;
const MAX_NAMED_TIME_ZONES = 16;
const MAX_WAVEFORM_SAMPLES = 640;
const MAX_FULL_SAMPLE_COUNT = 10_000_000;
const MAX_QUALITY_INTERVALS = 4_096;
const MAX_SPECTROGRAM_FREQUENCIES = 64;
const MAX_SPECTROGRAM_TIMES = 96;
const MAX_SPECTROGRAM_CELLS =
  MAX_SPECTROGRAM_FREQUENCIES * MAX_SPECTROGRAM_TIMES;
const MAX_EVENTS = 256;
const MAX_DERIVED_VALUES = 256;
const MAX_LIMITATIONS = 64;
const MAX_TIME_BASES = 16;
const MAX_SAMPLE_RATE_HZ = 1_000_000_000;
const MAX_ABSOLUTE_VALUE = 1_000_000_000_000_000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(
  record: Record<string, unknown>,
  allowedKeys: readonly string[],
): boolean {
  const allowed = new Set(allowedKeys);
  return Object.keys(record).every((key) => allowed.has(key));
}

function isFiniteNumber(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isFinite(value) &&
    Math.abs(value) <= MAX_ABSOLUTE_VALUE
  );
}

function isNonnegativeNumber(value: unknown): value is number {
  return isFiniteNumber(value) && value >= 0;
}

function isInteger(value: unknown): value is number {
  return isFiniteNumber(value) && Number.isSafeInteger(value);
}

function isNonnegativeInteger(value: unknown): value is number {
  return isInteger(value) && value >= 0;
}

function isBoundedString(
  value: unknown,
  maximumLength: number,
  allowEmpty = false,
): value is string {
  return (
    typeof value === "string" &&
    value.length <= maximumLength &&
    (allowEmpty || value.trim().length > 0)
  );
}

function isIdentifier(value: unknown): value is string {
  return typeof value === "string" && IDENTIFIER_PATTERN.test(value);
}

function isFilename(value: unknown): value is string {
  return (
    typeof value === "string" &&
    FILENAME_PATTERN.test(value) &&
    !value.includes("..")
  );
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && SHA256_PATTERN.test(value);
}

function isUtcTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    UTC_TIMESTAMP_PATTERN.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}

function isEnvironment(value: unknown): value is EnvironmentName {
  return value === "live" || value === "test";
}

function isBoundedStringArray(
  value: unknown,
  maximumItems: number,
  maximumItemLength: number,
  requireNonempty: boolean,
): value is string[] {
  return (
    Array.isArray(value) &&
    value.length <= maximumItems &&
    (!requireNonempty || value.length > 0) &&
    value.every((item) => isBoundedString(item, maximumItemLength))
  );
}

function isNumberArray(
  value: unknown,
  maximumItems: number,
  requireNonempty = true,
): value is number[] {
  return (
    Array.isArray(value) &&
    value.length <= maximumItems &&
    (!requireNonempty || value.length > 0) &&
    value.every(isFiniteNumber)
  );
}

function isStrictlyIncreasing(values: readonly number[]): boolean {
  return values.every((value, index) => index === 0 || value > values[index - 1]);
}

function isNondecreasing(values: readonly number[]): boolean {
  return values.every((value, index) => index === 0 || value >= values[index - 1]);
}

function hasUniqueValues(values: readonly string[]): boolean {
  return new Set(values).size === values.length;
}

function arraysEqual<T>(left: readonly T[], right: readonly T[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

function isWaveformSample(value: unknown): value is ActivityWaveformSample {
  if (!isRecord(value) || !hasOnlyKeys(value, SAMPLE_KEYS)) return false;
  return (
    isNonnegativeInteger(value.sampleIndex) &&
    isFiniteNumber(value.timeSeconds) &&
    isFiniteNumber(value.rawVoltageV) &&
    isFiniteNumber(value.calibratedVoltageV) &&
    isNonnegativeNumber(value.uncertaintyV) &&
    isFiniteNumber(value.residualVoltageV) &&
    isBoundedString(value.quality, MAX_LABEL_LENGTH)
  );
}

function isEvent(value: unknown): value is ActivityEventMarker {
  if (!isRecord(value) || !hasOnlyKeys(value, EVENT_KEYS)) return false;
  return (
    isIdentifier(value.eventId) &&
    isBoundedString(value.label, MAX_LABEL_LENGTH) &&
    isFiniteNumber(value.timeSeconds) &&
    isBoundedString(value.source, MAX_LABEL_LENGTH) &&
    isNonnegativeNumber(value.uncertaintySeconds)
  );
}

function isDerivedValue(value: unknown): value is ActivityDerivedValue {
  if (!isRecord(value) || !hasOnlyKeys(value, DERIVED_VALUE_KEYS)) return false;
  return (
    isIdentifier(value.valueId) &&
    isBoundedString(value.label, MAX_LABEL_LENGTH) &&
    isFiniteNumber(value.value) &&
    isBoundedString(value.unit, MAX_LABEL_LENGTH) &&
    isNonnegativeNumber(value.uncertainty)
  );
}

function isQualityInterval(
  value: unknown,
): value is { startSeconds: number; endSeconds: number; quality: string } {
  if (!isRecord(value) || !hasOnlyKeys(value, QUALITY_INTERVAL_KEYS)) return false;
  const startSeconds = value.startSeconds;
  const endSeconds = value.endSeconds;
  return (
    isFiniteNumber(startSeconds) &&
    isFiniteNumber(endSeconds) &&
    startSeconds <= endSeconds &&
    isBoundedString(value.quality, MAX_LABEL_LENGTH)
  );
}

function isNamedTimeZones(value: unknown): value is Record<string, string> {
  if (!isRecord(value)) return false;
  const entries = Object.entries(value);
  return (
    entries.length <= MAX_NAMED_TIME_ZONES &&
    entries.every(
      ([name, zone]) =>
        isBoundedString(name, MAX_LABEL_LENGTH) &&
        isBoundedString(zone, MAX_TIME_ZONE_LENGTH),
    )
  );
}

function isWaveform(value: unknown): value is ActivityScientificDataset["waveform"] {
  if (!isRecord(value) || !hasOnlyKeys(value, WAVEFORM_KEYS)) return false;
  if (
    !isNonnegativeInteger(value.fullSampleCount) ||
    value.fullSampleCount > MAX_FULL_SAMPLE_COUNT ||
    !isNonnegativeInteger(value.publishedSampleCount) ||
    !isFiniteNumber(value.startSeconds) ||
    !isFiniteNumber(value.endSeconds) ||
    value.startSeconds >= value.endSeconds ||
    !Array.isArray(value.samples) ||
    value.samples.length < 2 ||
    value.samples.length > MAX_WAVEFORM_SAMPLES ||
    !value.samples.every(isWaveformSample) ||
    !Array.isArray(value.qualityIntervals) ||
    value.qualityIntervals.length === 0 ||
    value.qualityIntervals.length > MAX_QUALITY_INTERVALS ||
    !value.qualityIntervals.every(isQualityInterval)
  ) {
    return false;
  }

  const samples = value.samples;
  const intervals = value.qualityIntervals;
  const startSeconds = value.startSeconds;
  const endSeconds = value.endSeconds;
  return (
    value.publishedSampleCount === samples.length &&
    value.fullSampleCount >= value.publishedSampleCount &&
    samples[0].sampleIndex === 0 &&
    samples[samples.length - 1].sampleIndex === value.fullSampleCount - 1 &&
    samples[0].timeSeconds === startSeconds &&
    samples[samples.length - 1].timeSeconds === endSeconds &&
    isStrictlyIncreasing(samples.map((sample) => sample.sampleIndex)) &&
    isStrictlyIncreasing(samples.map((sample) => sample.timeSeconds)) &&
    intervals[0].startSeconds === startSeconds &&
    intervals[intervals.length - 1].endSeconds === endSeconds &&
    intervals.every(
      (interval, index) =>
        interval.startSeconds >= startSeconds &&
        interval.endSeconds <= endSeconds &&
        (index === 0 || interval.startSeconds > intervals[index - 1].endSeconds),
    )
  );
}

function isSpectrogram(
  value: unknown,
  waveform: ActivityScientificDataset["waveform"],
  sampleRateHz: number,
): value is ActivityScientificDataset["spectrogram"] {
  if (!isRecord(value) || !hasOnlyKeys(value, SPECTROGRAM_KEYS)) return false;
  if (
    !isNumberArray(value.timeSeconds, MAX_SPECTROGRAM_TIMES) ||
    !isNumberArray(value.frequencyHz, MAX_SPECTROGRAM_FREQUENCIES) ||
    !Array.isArray(value.powerDb) ||
    value.powerDb.length === 0 ||
    value.powerDb.length > MAX_SPECTROGRAM_FREQUENCIES ||
    !value.powerDb.every((row) => isNumberArray(row, MAX_SPECTROGRAM_TIMES)) ||
    !isFiniteNumber(value.minimumDb) ||
    !isFiniteNumber(value.maximumDb) ||
    value.minimumDb > value.maximumDb ||
    !isBoundedString(value.units, MAX_LABEL_LENGTH)
  ) {
    return false;
  }

  const timeSeconds = value.timeSeconds;
  const frequencyHz = value.frequencyHz;
  const powerDb = value.powerDb;
  const cellCount = frequencyHz.length * timeSeconds.length;
  if (
    !isStrictlyIncreasing(timeSeconds) ||
    !isStrictlyIncreasing(frequencyHz) ||
    timeSeconds[0] < waveform.startSeconds ||
    timeSeconds[timeSeconds.length - 1] > waveform.endSeconds ||
    frequencyHz[0] < 0 ||
    frequencyHz[frequencyHz.length - 1] > sampleRateHz / 2 ||
    powerDb.length !== frequencyHz.length ||
    cellCount > MAX_SPECTROGRAM_CELLS ||
    !powerDb.every((row) => row.length === timeSeconds.length)
  ) {
    return false;
  }

  let actualMinimum = Number.POSITIVE_INFINITY;
  let actualMaximum = Number.NEGATIVE_INFINITY;
  for (const row of powerDb) {
    for (const cell of row) {
      actualMinimum = Math.min(actualMinimum, cell);
      actualMaximum = Math.max(actualMaximum, cell);
    }
  }
  return value.minimumDb === actualMinimum && value.maximumDb === actualMaximum;
}

export function isActivityScientificDataset(
  value: unknown,
): value is ActivityScientificDataset {
  if (!isRecord(value) || !hasOnlyKeys(value, DATASET_KEYS)) return false;
  if (
    value.schemaVersion !== "3.0.0" ||
    !isIdentifier(value.artifactId) ||
    !isIdentifier(value.visualizationId) ||
    !isEnvironment(value.environment) ||
    !isIdentifier(value.positionId) ||
    !isIdentifier(value.institutionId) ||
    !isBoundedString(value.title, MAX_LABEL_LENGTH) ||
    !isSha256(value.stateHeadHash) ||
    !isSha256(value.artifactDefinitionHash) ||
    !isSha256(value.inputDatasetHash) ||
    !isUtcTimestamp(value.generatedAt) ||
    !isUtcTimestamp(value.referenceTimeUtc) ||
    Date.parse(value.generatedAt) < Date.parse(value.referenceTimeUtc) ||
    !isFiniteNumber(value.sampleRateHz) ||
    value.sampleRateHz <= 0 ||
    value.sampleRateHz > MAX_SAMPLE_RATE_HZ ||
    !isIdentifier(value.sourceClockId) ||
    !isRecord(value.timeZones) ||
    !hasOnlyKeys(value.timeZones, TIME_ZONE_KEYS) ||
    !isBoundedString(value.timeZones.facility, MAX_TIME_ZONE_LENGTH) ||
    !isBoundedString(value.timeZones.source, MAX_TIME_ZONE_LENGTH) ||
    !isNamedTimeZones(value.timeZones.named) ||
    !isWaveform(value.waveform) ||
    !Array.isArray(value.events) ||
    value.events.length === 0 ||
    value.events.length > MAX_EVENTS ||
    !value.events.every(isEvent) ||
    !Array.isArray(value.derivedValues) ||
    value.derivedValues.length > MAX_DERIVED_VALUES ||
    !value.derivedValues.every(isDerivedValue) ||
    !isBoundedString(value.publicSummary, MAX_TEXT_LENGTH) ||
    !isBoundedStringArray(value.limitations, MAX_LIMITATIONS, MAX_TEXT_LENGTH, true)
  ) {
    return false;
  }

  const waveform = value.waveform;
  const eventIds = value.events.map((event) => event.eventId);
  const valueIds = value.derivedValues.map((derived) => derived.valueId);
  return (
    isSpectrogram(value.spectrogram, waveform, value.sampleRateHz) &&
    hasUniqueValues(eventIds) &&
    hasUniqueValues(valueIds) &&
    isNondecreasing(value.events.map((event) => event.timeSeconds)) &&
    value.events.every(
      (event) =>
        event.timeSeconds >= waveform.startSeconds &&
        event.timeSeconds <= waveform.endSeconds,
    )
  );
}

function isWaveformSeries(
  value: unknown,
  expectedId: ActivityWaveformSeriesId,
): value is ActivityWaveformSeries {
  if (!isRecord(value) || !hasOnlyKeys(value, SERIES_KEYS)) return false;
  return (
    value.id === expectedId &&
    isBoundedString(value.label, MAX_LABEL_LENGTH) &&
    isBoundedString(value.unit, MAX_LABEL_LENGTH) &&
    typeof value.defaultVisible === "boolean"
  );
}

function isTimeseriesView(value: unknown): value is ActivityLinkedTimeseriesView {
  if (!isRecord(value) || !hasOnlyKeys(value, TIMESERIES_VIEW_KEYS)) return false;
  if (
    value.id !== "waveform" ||
    value.type !== "linked-timeseries" ||
    value.x !== "timeSeconds" ||
    value.uncertaintyField !== "uncertaintyV" ||
    value.eventField !== "events" ||
    !Array.isArray(value.series) ||
    value.series.length !== 3
  ) {
    return false;
  }
  return (
    isWaveformSeries(value.series[0], "rawVoltageV") &&
    isWaveformSeries(value.series[1], "calibratedVoltageV") &&
    isWaveformSeries(value.series[2], "residualVoltageV")
  );
}

function isSpectrogramView(value: unknown): value is ActivityLinkedSpectrogramView {
  if (!isRecord(value) || !hasOnlyKeys(value, SPECTROGRAM_VIEW_KEYS)) return false;
  return (
    value.id === "spectrogram" &&
    value.type === "linked-spectrogram" &&
    value.x === "timeSeconds" &&
    value.y === "frequencyHz" &&
    value.value === "powerDb" &&
    isBoundedString(value.units, MAX_LABEL_LENGTH)
  );
}

export function isActivityVisualizationSpec(
  value: unknown,
): value is ActivityVisualizationSpec {
  if (!isRecord(value) || !hasOnlyKeys(value, SPEC_KEYS)) return false;
  if (
    value.schemaVersion !== "3.0.0" ||
    !isIdentifier(value.visualizationId) ||
    !isIdentifier(value.artifactId) ||
    !isEnvironment(value.environment) ||
    !isBoundedString(value.title, MAX_LABEL_LENGTH) ||
    value.renderer !== "missing-interior-native-svg-canvas" ||
    !isFilename(value.datasetFilename) ||
    !isFilename(value.fallbackFilename) ||
    !isFilename(value.manifestFilename) ||
    !Array.isArray(value.views) ||
    value.views.length !== 2 ||
    !isTimeseriesView(value.views[0]) ||
    !isSpectrogramView(value.views[1]) ||
    !isRecord(value.interaction) ||
    !hasOnlyKeys(value.interaction, INTERACTION_KEYS) ||
    !isRecord(value.provenance) ||
    !hasOnlyKeys(value.provenance, PROVENANCE_KEYS) ||
    !isBoundedStringArray(value.limitations, MAX_LIMITATIONS, MAX_TEXT_LENGTH, true)
  ) {
    return false;
  }

  const interaction = value.interaction;
  const provenance = value.provenance;
  return (
    typeof interaction.linkedTimeWindow === "boolean" &&
    typeof interaction.hoverReadout === "boolean" &&
    typeof interaction.dragToSelect === "boolean" &&
    typeof interaction.resetControl === "boolean" &&
    isBoundedStringArray(
      interaction.timeBases,
      MAX_TIME_BASES,
      MAX_LABEL_LENGTH,
      true,
    ) &&
    hasUniqueValues(interaction.timeBases) &&
    isSha256(provenance.stateHeadHash) &&
    isSha256(provenance.artifactDefinitionHash) &&
    isSha256(provenance.inputDatasetHash) &&
    isBoundedString(provenance.analysisMethod, MAX_LABEL_LENGTH) &&
    isBoundedString(provenance.analysisMethodVersion, MAX_LABEL_LENGTH)
  );
}

function isNullableFilename(value: unknown): value is string | null {
  return value === null || isFilename(value);
}

export function isScientificPublicationSummary(
  value: unknown,
): value is ScientificPublicationSummary {
  if (!isRecord(value) || !hasOnlyKeys(value, PUBLICATION_KEYS)) return false;
  if (
    !isEnvironment(value.environment) ||
    !isIdentifier(value.publicationId) ||
    !isIdentifier(value.artifactId) ||
    !isSha256(value.stateHeadHash) ||
    (value.evidenceStateHeadHash !== null &&
      !isSha256(value.evidenceStateHeadHash)) ||
    !isBoundedString(value.title, MAX_LABEL_LENGTH) ||
    !isBoundedString(value.publicSummary, MAX_TEXT_LENGTH) ||
    !isBoundedString(value.limitation, MAX_TEXT_LENGTH) ||
    !isFilename(value.primaryFilename) ||
    !isNullableFilename(value.manifestFilename) ||
    !isNullableFilename(value.visualizationFilename) ||
    !isNullableFilename(value.dataFilename) ||
    !isUtcTimestamp(value.publishedAt)
  ) {
    return false;
  }

  return (
    (value.visualizationFilename === null) === (value.dataFilename === null) &&
    (value.manifestFilename === null || value.manifestFilename !== value.primaryFilename)
  );
}

export function scientificBundleRecordsAgree(
  publication: ScientificPublicationSummary,
  spec: ActivityVisualizationSpec,
  dataset: ActivityScientificDataset,
): boolean {
  const evidenceStateHeadHash =
    publication.evidenceStateHeadHash ?? publication.stateHeadHash;
  return (
    publication.environment === spec.environment &&
    publication.environment === dataset.environment &&
    publication.artifactId === spec.artifactId &&
    publication.artifactId === dataset.artifactId &&
    spec.visualizationId === dataset.visualizationId &&
    evidenceStateHeadHash === spec.provenance.stateHeadHash &&
    evidenceStateHeadHash === dataset.stateHeadHash &&
    spec.provenance.artifactDefinitionHash === dataset.artifactDefinitionHash &&
    spec.provenance.inputDatasetHash === dataset.inputDatasetHash &&
    publication.title === spec.title &&
    publication.title === dataset.title &&
    publication.publicSummary === dataset.publicSummary &&
    publication.limitation === dataset.limitations[0] &&
    arraysEqual(spec.limitations, dataset.limitations) &&
    publication.primaryFilename === spec.fallbackFilename &&
    publication.manifestFilename === spec.manifestFilename &&
    publication.visualizationFilename !== null &&
    publication.dataFilename === spec.datasetFilename &&
    Date.parse(publication.publishedAt) >= Date.parse(dataset.generatedAt)
  );
}
