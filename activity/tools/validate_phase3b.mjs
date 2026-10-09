import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const spec = JSON.parse(await readFile(path.join(root, "examples", "activity-visualization.json"), "utf8"));
const data = JSON.parse(await readFile(path.join(root, "examples", "activity-data.json"), "utf8"));

const failures = [];
if (spec.schemaVersion !== "3.0.0") failures.push("spec schemaVersion");
if (data.schemaVersion !== "3.0.0") failures.push("data schemaVersion");
if (spec.artifactId !== data.artifactId) failures.push("artifactId agreement");
if (spec.visualizationId !== data.visualizationId) failures.push("visualizationId agreement");
if (spec.datasetFilename !== "activity-data.json") failures.push("dataset filename");
if (spec.manifestFilename !== "manifest-phase3b.json") failures.push("manifest filename");
if (!Array.isArray(data.waveform?.samples) || data.waveform.samples.length > 640) {
  failures.push("waveform sample bound");
}
if (!Array.isArray(data.spectrogram?.frequencyHz) || data.spectrogram.frequencyHz.length > 64) {
  failures.push("spectrogram frequency bound");
}
if (!Array.isArray(data.spectrogram?.timeSeconds) || data.spectrogram.timeSeconds.length > 96) {
  failures.push("spectrogram time bound");
}
if (data.spectrogram?.powerDb?.length !== data.spectrogram?.frequencyHz?.length) {
  failures.push("spectrogram row agreement");
}
if (failures.length) {
  console.error(JSON.stringify({ ok: false, failures }, null, 2));
  process.exitCode = 1;
} else {
  console.log(JSON.stringify({
    ok: true,
    artifactId: data.artifactId,
    visualizationId: data.visualizationId,
    waveformSamples: data.waveform.samples.length,
    spectrogramShape: [data.spectrogram.frequencyHz.length, data.spectrogram.timeSeconds.length],
  }, null, 2));
}
