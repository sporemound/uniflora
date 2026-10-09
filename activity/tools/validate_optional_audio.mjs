import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const activityRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const paths = {
  controller: resolve(activityRoot, "src/lib/audio-controller.ts"),
  console: resolve(activityRoot, "src/components/AudioConsole.tsx"),
  panel: resolve(activityRoot, "src/components/ScienceSonificationPanel.tsx"),
  mapping: resolve(activityRoot, "src/lib/science-sonification.ts"),
  app: resolve(activityRoot, "src/App.tsx"),
  lab: resolve(activityRoot, "src/components/FacilityScienceLab.tsx"),
  worker: resolve(activityRoot, "worker/index.ts"),
};
const entries = await Promise.all(
  Object.entries(paths).map(async ([name, path]) => [
    name,
    await readFile(path, "utf8"),
  ]),
);
const sources = Object.fromEntries(entries);
const audioSurface = [
  sources.controller,
  sources.console,
  sources.panel,
  sources.mapping,
].join("\n");

assert.match(
  sources.controller,
  /navigator\.userActivation[\s\S]*?\.isActive/u,
  "Audio activation must verify an active user gesture.",
);
assert.match(
  sources.controller,
  /sessionStorage/u,
  "Audio preferences must remain session-local.",
);
assert.doesNotMatch(
  audioSurface,
  /localStorage/u,
  "Optional audio must not persist a cross-session activation preference.",
);
assert.match(
  sources.controller,
  /visibilitychange/u,
  "Audio must react when the Activity enters the background.",
);
assert.match(
  sources.controller,
  /context\.suspend\s*\(/u,
  "Backgrounded or disabled audio must suspend its AudioContext.",
);
assert.match(
  sources.controller,
  /textAlternative\.trim\s*\(\)/u,
  "Every sound schedule must require a visible text equivalent.",
);
assert.match(
  sources.controller,
  /DynamicsCompressor/u,
  "The shared audio graph must retain its output limiter.",
);
assert.match(
  sources.controller,
  /analysis:\s*GainNode[\s\S]*presentation:\s*GainNode[\s\S]*master:\s*GainNode/u,
  "Analysis, presentation, and master gains must remain independent.",
);
assert.match(
  sources.console,
  /Audio never changes scoring or access/u,
  "The Audio Console must state that sound cannot affect progress.",
);
assert.match(
  sources.console,
  /No microphone or network\s+audio is used/u,
  "The Audio Console must state its microphone and network boundary.",
);
assert.match(
  sources.panel,
  /Listening never submits evidence, changes a result, or advances the game/u,
  "The scientific player must state that listening is non-authoritative.",
);
assert.match(
  sources.mapping,
  /audioRequiredForProgression:\s*false/u,
  "Scientific mappings must explicitly reject audio progression requirements.",
);
assert.match(
  sources.mapping,
  /No value is interpolated/u,
  "Scientific mappings must preserve missing and withheld gaps.",
);
assert.match(
  sources.app,
  /<AudioConsole\s+routeKey=/u,
  "The global optional Audio Console must remain mounted.",
);
assert.match(
  sources.lab,
  /<ScienceSonificationPanel/u,
  "Mapped scientific workstations must retain their sonification controls.",
);
assert.match(
  sources.worker,
  /microphone=\(\)/u,
  "The Activity permissions policy must continue to deny microphone access.",
);
assert.doesNotMatch(
  audioSurface,
  /\b(?:getUserMedia|MediaRecorder|SpeechRecognition|webkitSpeechRecognition|RTCPeerConnection)\b/u,
  "The optional audio surface must not capture or stream participant audio.",
);
assert.doesNotMatch(
  audioSurface,
  /\b(?:fetch|WebSocket|EventSource)\s*\(/u,
  "The optional audio surface must remain local and make no network requests.",
);
assert.doesNotMatch(
  audioSurface,
  /\bautoPlay\b|\bautoplay\b/u,
  "Optional audio must never autoplay.",
);

console.log(
  "Optional audio validation passed: explicit activation, session-only settings, visible equivalents, no progression dependency, no capture, no streaming, and no autoplay.",
);
