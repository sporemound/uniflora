export type AudioChannel = "analysis" | "presentation";

export type AudioEarcon =
  | "acknowledge"
  | "commit"
  | "transition"
  | "complete";

export type AudioWaveform = "sine" | "triangle" | "square" | "sawtooth";

export interface AudioTone {
  /**
   * Start time relative to the beginning of the schedule.
   */
  startSeconds: number;
  durationSeconds: number;
  frequencyHz: number;
  endFrequencyHz?: number;
  level?: number;
  waveform?: AudioWaveform;
  pan?: number;
}

export interface AudioSchedule {
  label: string;
  /**
   * A concise, visible equivalent of what the sound represents. A schedule
   * without this field is rejected at runtime as well as by TypeScript.
   */
  textAlternative: string;
  tones: readonly AudioTone[];
}

export type AudioContextState =
  | "uninitialized"
  | "running"
  | "suspended"
  | "closed"
  | "interrupted";

export interface AudioControllerState {
  supported: boolean;
  enabled: boolean;
  muted: boolean;
  contextState: AudioContextState;
  masterVolume: number;
  analysisVolume: number;
  presentationVolume: number;
  analysisPlaying: boolean;
  presentationPlaying: boolean;
  activeAnalysisLabel: string | null;
  statusMessage: string;
  previousSessionActivation: boolean;
}

interface StoredAudioPreferences {
  version: 1;
  masterVolume: number;
  analysisVolume: number;
  presentationVolume: number;
  wasEnabled: boolean;
}

interface AudioGraph {
  analysis: GainNode;
  presentation: GainNode;
  master: GainNode;
  limiter: DynamicsCompressorNode;
}

type AudioContextConstructor = new (
  contextOptions?: AudioContextOptions,
) => AudioContext;

type AudioListener = () => void;

const AUDIO_PREFERENCES_KEY = "uniflora.optional-audio.v1";
const DEFAULT_MASTER_VOLUME = 0.58;
const DEFAULT_ANALYSIS_VOLUME = 0.62;
const DEFAULT_PRESENTATION_VOLUME = 0.72;
const MAX_SCHEDULE_TONES = 512;
const MAX_SCHEDULE_SECONDS = 120;
const MIN_FREQUENCY_HZ = 32;
const MAX_FREQUENCY_HZ = 8_000;

const earconTones: Record<AudioEarcon, readonly AudioTone[]> = {
  acknowledge: [
    {
      startSeconds: 0,
      durationSeconds: 0.12,
      frequencyHz: 392,
      level: 0.12,
      waveform: "sine",
    },
  ],
  commit: [
    {
      startSeconds: 0,
      durationSeconds: 0.1,
      frequencyHz: 330,
      level: 0.1,
      waveform: "triangle",
    },
    {
      startSeconds: 0.12,
      durationSeconds: 0.13,
      frequencyHz: 440,
      level: 0.1,
      waveform: "triangle",
    },
  ],
  transition: [
    {
      startSeconds: 0,
      durationSeconds: 0.16,
      frequencyHz: 294,
      endFrequencyHz: 370,
      level: 0.09,
      waveform: "sine",
      pan: -0.12,
    },
    {
      startSeconds: 0.1,
      durationSeconds: 0.18,
      frequencyHz: 370,
      endFrequencyHz: 466,
      level: 0.09,
      waveform: "sine",
      pan: 0.12,
    },
  ],
  complete: [
    {
      startSeconds: 0,
      durationSeconds: 0.14,
      frequencyHz: 262,
      level: 0.08,
      waveform: "triangle",
    },
    {
      startSeconds: 0.12,
      durationSeconds: 0.16,
      frequencyHz: 330,
      level: 0.08,
      waveform: "triangle",
    },
    {
      startSeconds: 0.25,
      durationSeconds: 0.22,
      frequencyHz: 392,
      level: 0.09,
      waveform: "triangle",
    },
  ],
};

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function finiteOr(value: number, fallback: number): number {
  return Number.isFinite(value) ? value : fallback;
}

function volumeGain(volume: number): number {
  const normalized = clamp(finiteOr(volume, 0), 0, 1);
  return normalized * normalized;
}

function audioContextConstructor(): AudioContextConstructor | null {
  if (typeof window === "undefined") return null;

  const audioWindow = window as typeof window & {
    webkitAudioContext?: AudioContextConstructor;
  };
  return window.AudioContext ?? audioWindow.webkitAudioContext ?? null;
}

function readPreferences(): StoredAudioPreferences | null {
  if (typeof window === "undefined") return null;

  try {
    const raw = window.sessionStorage.getItem(AUDIO_PREFERENCES_KEY);
    if (!raw) return null;
    const candidate = JSON.parse(raw) as Partial<StoredAudioPreferences>;
    if (candidate.version !== 1) return null;

    return {
      version: 1,
      masterVolume: clamp(
        finiteOr(candidate.masterVolume ?? DEFAULT_MASTER_VOLUME, DEFAULT_MASTER_VOLUME),
        0,
        1,
      ),
      analysisVolume: clamp(
        finiteOr(
          candidate.analysisVolume ?? DEFAULT_ANALYSIS_VOLUME,
          DEFAULT_ANALYSIS_VOLUME,
        ),
        0,
        1,
      ),
      presentationVolume: clamp(
        finiteOr(
          candidate.presentationVolume ?? DEFAULT_PRESENTATION_VOLUME,
          DEFAULT_PRESENTATION_VOLUME,
        ),
        0,
        1,
      ),
      wasEnabled: candidate.wasEnabled === true,
    };
  } catch {
    return null;
  }
}

function hasActiveUserGesture(): boolean {
  if (typeof navigator === "undefined" || !navigator.userActivation) {
    return true;
  }
  return navigator.userActivation.isActive;
}

class OptionalAudioController {
  private readonly listeners = new Set<AudioListener>();
  private readonly analysisSources = new Set<AudioScheduledSourceNode>();
  private readonly presentationSources = new Set<AudioScheduledSourceNode>();
  private context: AudioContext | null = null;
  private graph: AudioGraph | null = null;
  private state: AudioControllerState;

  constructor() {
    const preferences = readPreferences();
    const supported = audioContextConstructor() !== null;
    this.state = {
      supported,
      enabled: false,
      muted: true,
      contextState: "uninitialized",
      masterVolume: preferences?.masterVolume ?? DEFAULT_MASTER_VOLUME,
      analysisVolume: preferences?.analysisVolume ?? DEFAULT_ANALYSIS_VOLUME,
      presentationVolume:
        preferences?.presentationVolume ?? DEFAULT_PRESENTATION_VOLUME,
      analysisPlaying: false,
      presentationPlaying: false,
      activeAnalysisLabel: null,
      statusMessage: supported
        ? "Optional audio is off. All information remains available on screen."
        : "Optional audio is unavailable in this browser. All information remains available on screen.",
      previousSessionActivation: preferences?.wasEnabled ?? false,
    };

    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", this.handleVisibilityChange);
    }
  }

  readonly subscribe = (listener: AudioListener): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  readonly getSnapshot = (): AudioControllerState => this.state;

  readonly getServerSnapshot = (): AudioControllerState => this.state;

  async enable(): Promise<boolean> {
    if (!this.state.supported) {
      this.update({
        statusMessage:
          "Optional audio is unavailable in this browser. All information remains available on screen.",
      });
      return false;
    }
    if (!hasActiveUserGesture()) {
      this.update({
        statusMessage:
          "Select Enable optional audio directly to start the audio engine.",
      });
      return false;
    }
    if (typeof document !== "undefined" && document.hidden) {
      this.update({
        statusMessage: "Return to this view before enabling optional audio.",
      });
      return false;
    }

    try {
      const context = this.ensureContext();
      if (context.state !== "running") {
        await context.resume();
      }
      if (context.state !== "running") {
        this.update({
          contextState: this.normalizedContextState(context.state),
          statusMessage:
            "The browser paused optional audio. Select Resume audio to try again.",
        });
        return false;
      }

      this.update({
        enabled: true,
        muted: false,
        contextState: "running",
        previousSessionActivation: true,
        statusMessage:
          "Optional audio is on. Every sound repeats information also shown on screen.",
      });
      this.applyVolumeSettings();
      this.storePreferences(true);
      return true;
    } catch {
      this.update({
        enabled: false,
        muted: true,
        statusMessage:
          "Optional audio could not be started. All controls and information remain available without it.",
      });
      return false;
    }
  }

  async resume(): Promise<boolean> {
    if (!this.state.enabled) {
      return this.enable();
    }
    if (!hasActiveUserGesture()) {
      this.update({
        statusMessage: "Select Resume audio directly to continue optional audio.",
      });
      return false;
    }
    if (typeof document !== "undefined" && document.hidden) return false;
    if (!this.context) return this.enable();

    try {
      await this.context.resume();
      const running = this.context.state === "running";
      this.update({
        contextState: this.normalizedContextState(this.context.state),
        statusMessage: running
          ? "Optional audio resumed. Every sound repeats information also shown on screen."
          : "The browser kept optional audio paused. All information remains available on screen.",
      });
      if (running) this.applyVolumeSettings();
      return running;
    } catch {
      this.update({
        statusMessage:
          "Optional audio could not resume. All information remains available on screen.",
      });
      return false;
    }
  }

  async disable(): Promise<void> {
    this.stopAll("Optional audio is off. All information remains available on screen.");
    this.update({
      enabled: false,
      muted: true,
      previousSessionActivation: false,
    });
    this.applyVolumeSettings();
    this.storePreferences(false);

    if (this.context?.state === "running") {
      try {
        await this.context.suspend();
      } catch {
        // A failed suspension is still silent because the master gain is zero.
      }
    }
    this.update({
      contextState: this.context
        ? this.normalizedContextState(this.context.state)
        : "uninitialized",
    });
  }

  async setMuted(muted: boolean): Promise<boolean> {
    if (muted) {
      this.stopAll("Optional audio is muted. All information remains available on screen.");
      this.update({ muted: true });
      this.applyVolumeSettings();
      return true;
    }

    if (!this.state.enabled) {
      return this.enable();
    }
    const resumed = await this.resume();
    if (!resumed) return false;

    this.update({
      muted: false,
      statusMessage:
        "Optional audio is unmuted. Every sound repeats information also shown on screen.",
    });
    this.applyVolumeSettings();
    return true;
  }

  setMasterVolume(volume: number): void {
    this.update({ masterVolume: clamp(finiteOr(volume, 0), 0, 1) });
    this.applyVolumeSettings();
    this.storePreferences(this.state.previousSessionActivation);
  }

  setAnalysisVolume(volume: number): void {
    this.update({ analysisVolume: clamp(finiteOr(volume, 0), 0, 1) });
    this.applyVolumeSettings();
    this.storePreferences(this.state.previousSessionActivation);
  }

  setPresentationVolume(volume: number): void {
    this.update({ presentationVolume: clamp(finiteOr(volume, 0), 0, 1) });
    this.applyVolumeSettings();
    this.storePreferences(this.state.previousSessionActivation);
  }

  playSchedule(schedule: AudioSchedule): boolean {
    const textAlternative = schedule.textAlternative.trim();
    const label = schedule.label.trim();
    if (!textAlternative) {
      this.update({
        statusMessage:
          "Analysis audio was not played because its visible text equivalent is missing.",
      });
      return false;
    }
    if (!this.canPlay()) return false;

    const tones = schedule.tones
      .slice(0, MAX_SCHEDULE_TONES)
      .filter(
        (tone) =>
          Number.isFinite(tone.startSeconds) &&
          Number.isFinite(tone.durationSeconds) &&
          Number.isFinite(tone.frequencyHz) &&
          tone.startSeconds >= 0 &&
          tone.startSeconds <= MAX_SCHEDULE_SECONDS &&
          tone.durationSeconds > 0,
      );
    if (tones.length === 0) {
      this.update({
        statusMessage:
          "Analysis audio was not played because the schedule contains no audible values.",
      });
      return false;
    }

    this.stopAnalysis(undefined, false);
    const context = this.context;
    const graph = this.graph;
    if (!context || !graph) return false;
    const scheduleStart = context.currentTime + 0.025;

    for (const tone of tones) {
      this.scheduleTone(
        tone,
        scheduleStart,
        graph.analysis,
        this.analysisSources,
        "analysis",
      );
    }

    this.update({
      analysisPlaying: this.analysisSources.size > 0,
      activeAnalysisLabel: label || "Data sonification",
      statusMessage: `Analysis audio: ${label || "Data sonification"}. On-screen equivalent: ${textAlternative}`,
    });
    return true;
  }

  stopAnalysis(
    message = "Analysis audio stopped. The visual and text display remains active.",
    announce = true,
  ): void {
    this.stopSources(this.analysisSources);
    this.update({
      analysisPlaying: false,
      activeAnalysisLabel: null,
      ...(announce ? { statusMessage: message } : {}),
    });
  }

  async playPresentationAudio(
    audioBytes: ArrayBuffer,
    textAlternative: string,
    label = "Hypha sealed-stone reply",
  ): Promise<boolean> {
    const visibleEquivalent = textAlternative.trim();
    if (!visibleEquivalent) {
      this.update({
        statusMessage:
          "Hypha audio was not played because its text equivalent is missing.",
      });
      return false;
    }
    if (!this.canPlay() || !this.context || !this.graph) return false;

    let buffer: AudioBuffer;
    try {
      buffer = await this.context.decodeAudioData(audioBytes.slice(0));
    } catch {
      this.update({
        statusMessage:
          "Hypha audio could not be decoded. The text fallback remains available.",
      });
      return false;
    }

    this.stopSources(this.presentationSources);
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.graph.presentation);
    this.presentationSources.add(source);
    source.addEventListener(
      "ended",
      () => {
        this.presentationSources.delete(source);
        source.disconnect();
        if (this.presentationSources.size === 0) {
          this.update({ presentationPlaying: false });
        }
      },
      { once: true },
    );
    source.start();
    this.update({
      presentationPlaying: true,
      statusMessage: `${label}. Text equivalent is available on request or failure.`,
    });
    return true;
  }

  playEarcon(earcon: AudioEarcon, textAlternative: string): boolean {
    const visibleEquivalent = textAlternative.trim();
    if (!visibleEquivalent) {
      this.update({
        statusMessage:
          "The audio cue was not played because its visible text equivalent is missing.",
      });
      return false;
    }
    if (!this.canPlay()) return false;

    const context = this.context;
    const graph = this.graph;
    if (!context || !graph) return false;
    this.stopSources(this.presentationSources);
    const start = context.currentTime + 0.015;
    for (const tone of earconTones[earcon]) {
      this.scheduleTone(
        tone,
        start,
        graph.presentation,
        this.presentationSources,
        "presentation",
      );
    }
    this.update({
      presentationPlaying: this.presentationSources.size > 0,
      statusMessage: `Optional audio cue. On-screen equivalent: ${visibleEquivalent}`,
    });
    return true;
  }

  stopAll(
    message = "Optional audio stopped. All information remains available on screen.",
  ): void {
    this.stopSources(this.analysisSources);
    this.stopSources(this.presentationSources);
    this.update({
      analysisPlaying: false,
      presentationPlaying: false,
      activeAnalysisLabel: null,
      statusMessage: message,
    });
  }

  stopForRouteChange(): void {
    if (!this.state.analysisPlaying && !this.state.presentationPlaying) return;
    this.stopAll(
      "Audio stopped when the view changed. All information remains available on screen.",
    );
  }

  private readonly handleVisibilityChange = (): void => {
    if (typeof document === "undefined" || !document.hidden || !this.context) {
      return;
    }

    this.stopAll(
      "Optional audio paused while the Activity was in the background. Select Resume audio to continue.",
    );
    if (this.context.state === "running") {
      void this.context
        .suspend()
        .catch(() => undefined)
        .finally(() => {
          if (!this.context) return;
          this.update({
            contextState: this.normalizedContextState(this.context.state),
          });
        });
    }
  };

  private ensureContext(): AudioContext {
    if (this.context) return this.context;

    const Context = audioContextConstructor();
    if (!Context) throw new Error("Web Audio is not supported.");
    const context = new Context({ latencyHint: "interactive" });
    const analysis = context.createGain();
    const presentation = context.createGain();
    const master = context.createGain();
    const limiter = context.createDynamicsCompressor();

    limiter.threshold.value = -5;
    limiter.knee.value = 8;
    limiter.ratio.value = 12;
    limiter.attack.value = 0.003;
    limiter.release.value = 0.18;
    analysis.connect(master);
    presentation.connect(master);
    master.connect(limiter);
    limiter.connect(context.destination);

    this.context = context;
    this.graph = { analysis, presentation, master, limiter };
    context.addEventListener("statechange", () => {
      this.update({
        contextState: this.normalizedContextState(context.state),
      });
    });
    this.applyVolumeSettings();
    this.update({
      contextState: this.normalizedContextState(context.state),
    });
    return context;
  }

  private canPlay(): boolean {
    if (
      !this.state.enabled ||
      this.state.muted ||
      !this.context ||
      !this.graph ||
      this.context.state !== "running" ||
      (typeof document !== "undefined" && document.hidden)
    ) {
      return false;
    }
    return true;
  }

  private scheduleTone(
    tone: AudioTone,
    scheduleStart: number,
    destination: AudioNode,
    sourceSet: Set<AudioScheduledSourceNode>,
    channel: AudioChannel,
  ): void {
    if (!this.context) return;
    const context = this.context;
    const oscillator = context.createOscillator();
    const envelope = context.createGain();
    const panner = context.createStereoPanner();
    const start = scheduleStart + clamp(tone.startSeconds, 0, MAX_SCHEDULE_SECONDS);
    const duration = clamp(tone.durationSeconds, 0.035, 12);
    const end = start + duration;
    const attack = Math.min(0.012, duration * 0.24);
    const release = Math.min(0.035, duration * 0.3);
    const level = clamp(finiteOr(tone.level ?? 0.1, 0.1), 0.002, 0.24);
    const frequency = clamp(
      finiteOr(tone.frequencyHz, 220),
      MIN_FREQUENCY_HZ,
      MAX_FREQUENCY_HZ,
    );
    const endFrequency = clamp(
      finiteOr(tone.endFrequencyHz ?? frequency, frequency),
      MIN_FREQUENCY_HZ,
      MAX_FREQUENCY_HZ,
    );

    oscillator.type = tone.waveform ?? "sine";
    oscillator.frequency.setValueAtTime(frequency, start);
    if (endFrequency !== frequency) {
      oscillator.frequency.linearRampToValueAtTime(endFrequency, end);
    }
    panner.pan.value = clamp(finiteOr(tone.pan ?? 0, 0), -0.85, 0.85);
    envelope.gain.setValueAtTime(0.0001, start);
    envelope.gain.exponentialRampToValueAtTime(level, start + attack);
    envelope.gain.setValueAtTime(level, Math.max(start + attack, end - release));
    envelope.gain.exponentialRampToValueAtTime(0.0001, end);

    oscillator.connect(envelope);
    envelope.connect(panner);
    panner.connect(destination);
    sourceSet.add(oscillator);
    oscillator.addEventListener(
      "ended",
      () => {
        sourceSet.delete(oscillator);
        oscillator.disconnect();
        envelope.disconnect();
        panner.disconnect();
        if (sourceSet.size === 0) {
          this.update(
            channel === "analysis"
              ? { analysisPlaying: false, activeAnalysisLabel: null }
              : { presentationPlaying: false },
          );
        }
      },
      { once: true },
    );
    oscillator.start(start);
    oscillator.stop(end + 0.01);
  }

  private stopSources(sources: Set<AudioScheduledSourceNode>): void {
    for (const source of [...sources]) {
      try {
        source.stop();
      } catch {
        // Already-ended sources are removed by their ended handler.
      }
    }
  }

  private applyVolumeSettings(): void {
    if (!this.context || !this.graph) return;
    const now = this.context.currentTime;
    const masterTarget =
      this.state.enabled && !this.state.muted
        ? volumeGain(this.state.masterVolume)
        : 0;
    const setGain = (gain: GainNode, target: number) => {
      gain.gain.cancelScheduledValues(now);
      gain.gain.setTargetAtTime(target, now, 0.012);
    };
    setGain(this.graph.master, masterTarget);
    setGain(this.graph.analysis, volumeGain(this.state.analysisVolume));
    setGain(
      this.graph.presentation,
      volumeGain(this.state.presentationVolume),
    );
  }

  private storePreferences(wasEnabled: boolean): void {
    if (typeof window === "undefined") return;
    const preferences: StoredAudioPreferences = {
      version: 1,
      masterVolume: this.state.masterVolume,
      analysisVolume: this.state.analysisVolume,
      presentationVolume: this.state.presentationVolume,
      wasEnabled,
    };
    try {
      window.sessionStorage.setItem(
        AUDIO_PREFERENCES_KEY,
        JSON.stringify(preferences),
      );
    } catch {
      // Sandboxed browsers may deny storage. The in-memory controls still work.
    }
  }

  private normalizedContextState(state: string): AudioContextState {
    if (
      state === "running" ||
      state === "suspended" ||
      state === "closed" ||
      state === "interrupted"
    ) {
      return state;
    }
    return "uninitialized";
  }

  private update(patch: Partial<AudioControllerState>): void {
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) listener();
  }
}

export const audioController = new OptionalAudioController();
