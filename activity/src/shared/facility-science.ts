import type { PublicAnomalyMapLayer } from "./geospatial";
import {
  ENVIRONMENTAL_FACILITIES,
  type EnvironmentalFacilityId,
} from "./environmental-context";

export interface ScienceControl {
  id: string;
  readingId: string;
  label: string;
  minimum: number;
  maximum: number;
  step: number;
  unit: string;
  initial: number;
  teaches: string;
}

export interface ScienceTool {
  id: string;
  label: string;
  focus: string;
}

export interface ScienceConcept {
  title: string;
  explanation: string;
  readingId: string;
}

export interface ScienceReading {
  id: string;
  title: string;
  source: string;
  url: string;
  access: string;
}

export interface FacilityScienceDefinition {
  code: string;
  title: string;
  discipline: string;
  controls: readonly ScienceControl[];
  tools: readonly ScienceTool[];
  concepts: readonly ScienceConcept[];
  readings: readonly ScienceReading[];
  equation: string;
  equationGuide: string;
  equationReadingId: string;
  predictionPrompt: string;
  predictionOptions: readonly string[];
  misconception: string;
  correction: string;
  sourceUses: readonly string[];
  withholdingLabel: string;
}

export interface ScienceMetric {
  label: string;
  value: string;
  detail: string;
  readingId: string;
}

export interface ScienceRecord {
  channel: string;
  reading: string;
  retained: boolean;
}

export interface SciencePoint {
  x: number;
  y: number;
  group: number;
  uncertainty?: number;
}

export interface FacilityScienceFrame {
  metrics: ScienceMetric[];
  records: ScienceRecord[];
  series: Record<string, number[]>;
  matrix: number[][];
  points: SciencePoint[];
  bars: number[];
  method: string;
  observation: string;
  mapLayers: PublicAnomalyMapLayer[];
}

export type ScienceControlValues = Record<string, number>;

export const FACILITY_SCIENCE: Record<
  EnvironmentalFacilityId,
  FacilityScienceDefinition
> = {
  boundary_array: {
    code: "BA-01",
    title: "Signal timing laboratory",
    discipline: "Waves · sampling · spectra · correlation · propagation",
    controls: [
      {
        id: "clockCorrection",
        readingId: "ba_correlation",
        label: "Radio-clock correction",
        minimum: -60,
        maximum: 60,
        step: 1,
        unit: " ms",
        initial: 0,
        teaches: "Cross-correlation estimates a relative delay; it does not establish a cause.",
      },
      {
        id: "sampleRate",
        readingId: "ba_sampling",
        label: "Sampling rate",
        minimum: 24,
        maximum: 128,
        step: 4,
        unit: " Hz",
        initial: 64,
        teaches: "A sampler must run above twice the highest frequency to avoid aliasing.",
      },
      {
        id: "filterCutoff",
        readingId: "ba_signals",
        label: "Low-pass cutoff",
        minimum: 6,
        maximum: 30,
        step: 1,
        unit: " Hz",
        initial: 24,
        teaches: "Filtering can improve signal-to-noise while also erasing real structure.",
      },
      {
        id: "noiseLevel",
        readingId: "ba_signals",
        label: "Acquisition noise",
        minimum: 0,
        maximum: 100,
        step: 1,
        unit: "%",
        initial: 18,
        teaches: "Noise changes uncertainty and residuals without changing the injected frequencies.",
      },
      {
        id: "clockDrift",
        readingId: "ba_clock_drift",
        label: "Relative clock drift",
        minimum: -500,
        maximum: 500,
        step: 10,
        unit: " ppm",
        initial: 0,
        teaches: "A fixed correction cannot align a clock whose rate differs over the observation window.",
      },
    ],
    tools: [
      { id: "oscilloscope", label: "Oscilloscope", focus: "Compare synchronized time-domain signals." },
      { id: "spectrum", label: "Spectrum", focus: "Inspect frequency energy and the Nyquist boundary." },
      { id: "correlation", label: "Lag scan", focus: "Measure alignment and residual error across trial lags." },
    ],
    concepts: [
      { title: "Sampling and aliasing", explanation: "Discrete samples can misrepresent frequencies above half the sampling rate.", readingId: "ba_sampling" },
      { title: "Fourier spectrum", explanation: "A time signal can be represented by the strength of its frequency components.", readingId: "ba_signals" },
      { title: "Cross-correlation", explanation: "Sliding one signal against another reveals the delay with the strongest resemblance.", readingId: "ba_correlation" },
      { title: "Propagation", explanation: "A delay can arise from clocks, path length, processing, or the medium between instruments.", readingId: "ba_waves" },
    ],
    readings: [
      {
        id: "ba_sampling",
        title: "Sampling and the Discrete Fourier Transform",
        source: "MIT OpenCourseWare",
        url: "https://ocw.mit.edu/courses/2-161-signal-processing-continuous-and-discrete-fall-2008/resources/lecture_10/",
        access: "Free course handout · CC BY-NC-SA 4.0",
      },
      {
        id: "ba_signals",
        title: "Signals and Systems",
        source: "MIT OpenCourseWare",
        url: "https://ocw.mit.edu/courses/res-6-007-signals-and-systems-spring-2011/",
        access: "Free course materials · CC BY-NC-SA 4.0",
      },
      {
        id: "ba_waves",
        title: "Mathematics of Waves",
        source: "OpenStax University Physics",
        url: "https://openstax.org/books/university-physics-volume-1/pages/16-2-mathematics-of-waves",
        access: "Free textbook · CC BY-NC-SA 4.0",
      },
      {
        id: "ba_correlation",
        title: "Cross-correlate Two N-dimensional Arrays",
        source: "SciPy documentation",
        url: "https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.correlate.html",
        access: "Free open-source documentation · BSD-3-Clause",
      },
      {
        id: "ba_clock_drift",
        title: "Time and Frequency from A to Z: F",
        source: "National Institute of Standards and Technology",
        url: "https://www.nist.gov/pml/time-and-frequency-division/popular-links/time-frequency-z/time-and-frequency-z-f",
        access: "Free public U.S. government educational resource",
      },
    ],
    equation: "Rxy(τ) = Σ x(t) y(t + τ)",
    equationGuide: "Rxy is similarity at trial delay τ. Its maximum estimates relative alignment.",
    equationReadingId: "ba_correlation",
    predictionPrompt: "If the sampling rate drops below twice the 19.5 Hz component, what should happen to its measured spectral location?",
    predictionOptions: ["It aliases", "It stays exact", "It disappears completely"],
    misconception: "The largest correlation peak proves both instruments observed the same physical source.",
    correction: "Correlation measures resemblance and timing. Shared interference, copied processing, or a common clock can create the same peak.",
    sourceUses: ["NWS visibility and pressure", "NOAA SWPC propagation conditions", "USGS exclusion window"],
    withholdingLabel: "Withhold the radio return",
  },
  aeronautical_incident_center: {
    code: "AI-02",
    title: "Kinematics and sensor-fusion laboratory",
    discipline: "Motion · triangulation · uncertainty · filtering · wind",
    controls: [
      {
        id: "fusionWeight",
        readingId: "ai_kalman",
        label: "Transponder trust",
        minimum: 0,
        maximum: 100,
        step: 1,
        unit: "%",
        initial: 58,
        teaches: "A fused estimate changes when the assumed reliability of a feed changes.",
      },
      {
        id: "windCorrection",
        readingId: "ai_motion",
        label: "Crosswind correction",
        minimum: -35,
        maximum: 35,
        step: 1,
        unit: " kt",
        initial: 0,
        teaches: "Ground track and air-relative motion differ in moving air.",
      },
      {
        id: "measurementNoise",
        readingId: "ai_estimation",
        label: "Position uncertainty",
        minimum: 1,
        maximum: 20,
        step: 0.5,
        unit: " km",
        initial: 6,
        teaches: "Uncertainty must travel through triangulation and fusion, not vanish at the display.",
      },
      {
        id: "clockLatency",
        readingId: "ai_gps",
        label: "Feed latency",
        minimum: -20,
        maximum: 20,
        step: 0.5,
        unit: " s",
        initial: 0,
        teaches: "A timestamp error can look like a spatial offset along a moving track.",
      },
      {
        id: "processNoise",
        readingId: "ai_estimation",
        label: "Maneuver process noise",
        minimum: 0,
        maximum: 100,
        step: 1,
        unit: "%",
        initial: 22,
        teaches: "Process noise declares how much unmodeled acceleration the estimator permits.",
      },
    ],
    tools: [
      { id: "tracks", label: "Track map", focus: "Compare independent and fused trajectories." },
      { id: "residuals", label: "Residual timeline", focus: "Look for structured disagreement between feeds." },
      { id: "covariance", label: "Uncertainty field", focus: "Inspect how measurement noise expands position bounds." },
    ],
    concepts: [
      { title: "Kinematics", explanation: "Position differences over time give velocity; changes in velocity give acceleration.", readingId: "ai_motion" },
      { title: "Triangulation", explanation: "Intersecting bearings constrain a location, but shallow intersection angles amplify error.", readingId: "ai_triangulation" },
      { title: "Sensor fusion", explanation: "Combining feeds requires declared weights, dependencies, and uncertainty models.", readingId: "ai_estimation" },
      { title: "Residual analysis", explanation: "A residual is observed minus predicted. Patterns in residuals expose model failure.", readingId: "ai_kalman" },
    ],
    readings: [
      {
        id: "ai_motion",
        title: "Relative Motion in Two Dimensions",
        source: "OpenStax University Physics",
        url: "https://openstax.org/books/university-physics-volume-1/pages/4-5-relative-motion-in-one-and-two-dimensions",
        access: "Free textbook · CC BY-NC-SA 4.0",
      },
      {
        id: "ai_triangulation",
        title: "Triangulation",
        source: "NOAA National Geodetic Survey",
        url: "https://www.ngs.noaa.gov/INFO/history/triangulation.shtml",
        access: "Free public U.S. government educational resource",
      },
      {
        id: "ai_gps",
        title: "Principles of the Global Positioning System",
        source: "MIT OpenCourseWare",
        url: "https://ocw.mit.edu/courses/12-540-principles-of-the-global-positioning-system-spring-2012/",
        access: "Free course materials · CC BY-NC-SA 4.0",
      },
      {
        id: "ai_estimation",
        title: "Stochastic Estimation and Control",
        source: "MIT OpenCourseWare",
        url: "https://ocw.mit.edu/courses/16-322-stochastic-estimation-and-control-fall-2004/",
        access: "Free course materials · CC BY-NC-SA 4.0",
      },
      {
        id: "ai_kalman",
        title: "The Kalman Filter",
        source: "MIT OpenCourseWare",
        url: "https://ocw.mit.edu/courses/2-154-maneuvering-and-control-of-surface-and-underwater-vehicles-13-49-fall-2004/resources/lec20/",
        access: "Free textbook chapter · CC BY-NC-SA 4.0",
      },
    ],
    equation: "x̂ = Kz + (1 − K)x₀",
    equationGuide: "The estimate x̂ blends measurement z and prior x₀ through trust weight K.",
    equationReadingId: "ai_kalman",
    predictionPrompt: "If position uncertainty increases while the observations stay fixed, what should happen to the position envelope?",
    predictionOptions: ["It expands", "It contracts", "It remains identical"],
    misconception: "A smooth fused track is automatically more accurate than every contributing feed.",
    correction: "Smoothing can hide contradictions. A fused product can be precise-looking while inheriting bias or dependence.",
    sourceUses: ["NWS wind and visibility", "NOAA SWPC radio conditions", "Independent feed timestamps"],
    withholdingLabel: "Withhold the fused display",
  },
  aerial_phenomena_archive: {
    code: "AP-03",
    title: "Recurrence and provenance laboratory",
    discipline: "Similarity · clustering · networks · base rates · selection bias",
    controls: [
      {
        id: "similarityThreshold",
        readingId: "ap_clustering",
        label: "Similarity threshold",
        minimum: 40,
        maximum: 98,
        step: 1,
        unit: "%",
        initial: 72,
        teaches: "A cluster count depends on the decision boundary used to call two records similar.",
      },
      {
        id: "timeWindow",
        readingId: "ap_probability",
        label: "Comparison window",
        minimum: 5,
        maximum: 80,
        step: 1,
        unit: " yr",
        initial: 35,
        teaches: "Changing the observation window changes both the numerator and the relevant base rate.",
      },
      {
        id: "provenanceWeight",
        readingId: "ap_provenance",
        label: "Source-independence weight",
        minimum: 0,
        maximum: 100,
        step: 1,
        unit: "%",
        initial: 70,
        teaches: "Copied descendants must not be counted as independent recurrence.",
      },
      {
        id: "geographicRadius",
        readingId: "ap_probability",
        label: "Geographic comparison radius",
        minimum: 100,
        maximum: 2_500,
        step: 50,
        unit: " km",
        initial: 1_200,
        teaches: "A wider search radius increases both candidate matches and the chance-match baseline.",
      },
      {
        id: "exposureNormalization",
        readingId: "ap_sampling",
        label: "Collection-exposure correction",
        minimum: 0,
        maximum: 100,
        step: 1,
        unit: "%",
        initial: 60,
        teaches: "Raw counts and exposure-normalized rates answer different questions.",
      },
    ],
    tools: [
      { id: "network", label: "Dependency network", focus: "Separate source ancestry from apparent recurrence." },
      { id: "chronology", label: "Chronology", focus: "Compare event density across unequal collection periods." },
      { id: "similarity", label: "Similarity matrix", focus: "See how thresholds and feature weights produce clusters." },
    ],
    concepts: [
      { title: "Feature distance", explanation: "Similarity is computed from selected features and their weights; it is not an intrinsic property.", readingId: "ap_clustering" },
      { title: "Network dependence", explanation: "A citation or copying graph reveals records that are not independent samples.", readingId: "ap_provenance" },
      { title: "Base-rate reasoning", explanation: "A striking match must be compared with how often such matches occur in the full search space.", readingId: "ap_probability" },
      { title: "Selection bias", explanation: "Archives preserve what institutions collected, retained, indexed, and released.", readingId: "ap_sampling" },
    ],
    readings: [
      {
        id: "ap_clustering",
        title: "Clustering",
        source: "scikit-learn documentation",
        url: "https://scikit-learn.org/stable/modules/clustering.html",
        access: "Free open-source documentation · BSD-3-Clause",
      },
      {
        id: "ap_provenance",
        title: "PROV Model Primer",
        source: "World Wide Web Consortium",
        url: "https://www.w3.org/TR/prov-primer/",
        access: "Free public technical recommendation",
      },
      {
        id: "ap_probability",
        title: "Introduction to Probability and Statistics",
        source: "MIT OpenCourseWare",
        url: "https://ocw.mit.edu/courses/18-05-introduction-to-probability-and-statistics-spring-2022/",
        access: "Free course materials · CC BY-NC-SA 4.0",
      },
      {
        id: "ap_sampling",
        title: "Data, Sampling, and Variation",
        source: "OpenStax Introductory Statistics",
        url: "https://openstax.org/books/introductory-statistics-2e/pages/1-2-data-sampling-and-variation-in-data-and-sampling",
        access: "Free textbook · CC BY-NC-SA 4.0",
      },
    ],
    equation: "d(x,y) = √Σ wi(xi − yi)²",
    equationGuide: "Weighted distance changes when feature weights wi change; clustering follows those choices.",
    equationReadingId: "ap_clustering",
    predictionPrompt: "If copied descendants are removed, what should usually happen to the apparent recurrence count?",
    predictionOptions: ["It decreases", "It increases", "It must stay fixed"],
    misconception: "Many similar records necessarily represent many independent events.",
    correction: "One source can generate many descendants. Independence must be established through provenance, not visual similarity.",
    sourceUses: ["Public-report timeline", "USGS event context", "Collection and accession metadata"],
    withholdingLabel: "Remove documented copy descendants",
  },
  holography_laboratory: {
    code: "HL-04",
    title: "Inverse reconstruction laboratory",
    discipline: "Interference · phase · tomography · sampling · regularization",
    controls: [
      {
        id: "angularCoverage",
        readingId: "hl_radon",
        label: "Angular coverage",
        minimum: 20,
        maximum: 100,
        step: 1,
        unit: "%",
        initial: 78,
        teaches: "Missing angles leave directions in the reconstruction weakly constrained.",
      },
      {
        id: "phaseOffset",
        readingId: "hl_holography",
        label: "Registration phase",
        minimum: -180,
        maximum: 180,
        step: 2,
        unit: "°",
        initial: 0,
        teaches: "Phase errors move interference structure even when intensity looks similar.",
      },
      {
        id: "regularization",
        readingId: "hl_inverse",
        label: "Regularization strength",
        minimum: 0,
        maximum: 100,
        step: 1,
        unit: "%",
        initial: 35,
        teaches: "Regularization trades noise suppression for model-imposed smoothness.",
      },
      {
        id: "projectionCount",
        readingId: "hl_radon",
        label: "Projection count",
        minimum: 8,
        maximum: 64,
        step: 2,
        unit: "",
        initial: 32,
        teaches: "More independent projection angles add constraints; repeated angles do not add the same information.",
      },
      {
        id: "phaseNoise",
        readingId: "hl_holography",
        label: "Phase noise",
        minimum: 0,
        maximum: 100,
        step: 1,
        unit: "%",
        initial: 12,
        teaches: "Phase uncertainty spreads into the reconstructed spatial field and its holdout residual.",
      },
    ],
    tools: [
      { id: "sinogram", label: "Projection set", focus: "Inspect measured line integrals over angle." },
      { id: "reconstruction", label: "Reconstruction", focus: "Compare supported structure with limited-angle artifacts." },
      { id: "residual", label: "Residual test", focus: "Withhold projections and test prediction error." },
    ],
    concepts: [
      { title: "Interference and phase", explanation: "Relative phase determines whether waves add or cancel.", readingId: "hl_interference" },
      { title: "Inverse problems", explanation: "Reconstruction infers hidden structure from indirect measurements and may have multiple solutions.", readingId: "hl_inverse" },
      { title: "Angular sampling", explanation: "Projection diversity determines which spatial directions are constrained.", readingId: "hl_radon" },
      { title: "Regularization", explanation: "A stabilizing assumption can reduce noise while introducing bias.", readingId: "hl_inverse" },
    ],
    readings: [
      {
        id: "hl_interference",
        title: "Young's Double-Slit Interference",
        source: "OpenStax University Physics",
        url: "https://openstax.org/books/university-physics-volume-3/pages/3-1-youngs-double-slit-interference",
        access: "Free textbook · CC BY-NC-SA 4.0",
      },
      {
        id: "hl_holography",
        title: "Holography",
        source: "OpenStax University Physics",
        url: "https://openstax.org/books/university-physics-volume-3/pages/4-7-holography",
        access: "Free textbook · CC BY-NC-SA 4.0",
      },
      {
        id: "hl_radon",
        title: "Radon Transform and Tomographic Reconstruction",
        source: "scikit-image documentation",
        url: "https://scikit-image.org/docs/stable/auto_examples/transform/plot_radon_transform.html",
        access: "Free open-source documentation and notebook · BSD-3-Clause",
      },
      {
        id: "hl_resolution",
        title: "Circular Apertures and Resolution",
        source: "OpenStax University Physics",
        url: "https://openstax.org/books/university-physics-volume-3/pages/4-5-circular-apertures-and-resolution",
        access: "Free textbook · CC BY-NC-SA 4.0",
      },
      {
        id: "hl_inverse",
        title: "Inverse Problems",
        source: "MIT OpenCourseWare",
        url: "https://ocw.mit.edu/courses/2-717j-optical-engineering-spring-2002/pages/syllabus/inverse/",
        access: "Free course materials · CC BY-NC-SA 4.0",
      },
    ],
    equation: "pθ(s) = ∫ f(x,y) ds",
    equationGuide: "A projection pθ is a line integral through field f at angle θ; reconstruction attempts the inverse.",
    equationReadingId: "hl_radon",
    predictionPrompt: "When angular coverage is reduced, what should happen to withheld-view residuals?",
    predictionOptions: ["They usually grow", "They become zero", "They are guaranteed unchanged"],
    misconception: "A visually sharp reconstruction proves that every interior feature was measured.",
    correction: "Sharpness can come from priors and regularization. Withholding tests reveal what the measurements actually constrain.",
    sourceUses: ["NWS visibility", "Atmospheric attenuation", "Projection registration metadata"],
    withholdingLabel: "Withhold one projection family",
  },
  subsurface_resonance_station: {
    code: "SR-05",
    title: "Wave and Earth-system laboratory",
    discipline: "Resonance · dispersion · seismology · acoustics · coupled systems",
    controls: [
      {
        id: "trialFrequency",
        readingId: "sr_forced",
        label: "Trial frequency",
        minimum: 1,
        maximum: 24,
        step: 0.5,
        unit: " Hz",
        initial: 8.5,
        teaches: "Resonance occurs when forcing overlaps a system mode; peak frequency alone does not identify the source.",
      },
      {
        id: "waveVelocity",
        readingId: "sr_wave_speed",
        label: "Wave velocity",
        minimum: 2,
        maximum: 8,
        step: 0.1,
        unit: " km/s",
        initial: 4.8,
        teaches: "Travel time becomes depth only through a velocity model.",
      },
      {
        id: "damping",
        readingId: "sr_damping",
        label: "Damping",
        minimum: 1,
        maximum: 100,
        step: 1,
        unit: "%",
        initial: 24,
        teaches: "Damping broadens resonance peaks and shortens persistence.",
      },
      {
        id: "depthRange",
        readingId: "sr_depth",
        label: "Maximum modeled depth",
        minimum: 6,
        maximum: 30,
        step: 1,
        unit: " km",
        initial: 18,
        teaches: "A search boundary can truncate compatible solutions and must be declared.",
      },
      {
        id: "coherenceWindow",
        readingId: "sr_coherence",
        label: "Coherence window",
        minimum: 1,
        maximum: 20,
        step: 1,
        unit: " s",
        initial: 8,
        teaches: "Longer windows improve frequency resolution while hiding short-lived change.",
      },
    ],
    tools: [
      { id: "depthFrequency", label: "Depth-frequency field", focus: "Locate modal ridges across trial depth." },
      { id: "spectrum", label: "Mode spectrum", focus: "Compare resonant peaks and damping width." },
      { id: "stations", label: "Station coherence", focus: "Test whether a mode survives sensor withholding." },
    ],
    concepts: [
      { title: "Resonance", explanation: "A driven system responds strongly near a natural frequency.", readingId: "sr_standing" },
      { title: "Wave velocity", explanation: "Material stiffness and density govern propagation speed.", readingId: "sr_wave_speed" },
      { title: "Dispersion", explanation: "Different frequencies can travel at different speeds, changing a waveform with distance.", readingId: "sr_dispersion" },
      { title: "Multiphysics coupling", explanation: "Seismic, acoustic, electromagnetic, groundwater, and infrastructure signals can share drivers.", readingId: "sr_multiphysics" },
    ],
    readings: [
      {
        id: "sr_forced",
        title: "Forced Oscillations",
        source: "OpenStax University Physics",
        url: "https://openstax.org/books/university-physics-volume-1/pages/15-6-forced-oscillations",
        access: "Free textbook · CC BY-NC-SA 4.0",
      },
      {
        id: "sr_damping",
        title: "Damped Oscillations",
        source: "OpenStax University Physics",
        url: "https://openstax.org/books/university-physics-volume-1/pages/15-5-damped-oscillations",
        access: "Free textbook · CC BY-NC-SA 4.0",
      },
      {
        id: "sr_standing",
        title: "Standing Waves and Resonance",
        source: "OpenStax University Physics",
        url: "https://openstax.org/books/university-physics-volume-1/pages/16-6-standing-waves-and-resonance",
        access: "Free textbook · CC BY-NC-SA 4.0",
      },
      {
        id: "sr_wave_speed",
        title: "Traveling Waves",
        source: "OpenStax University Physics",
        url: "https://openstax.org/books/university-physics-volume-1/pages/16-1-traveling-waves",
        access: "Free textbook · CC BY-NC-SA 4.0",
      },
      {
        id: "sr_seismographs",
        title: "Seismographs—Keeping Track of Earthquakes",
        source: "U.S. Geological Survey",
        url: "https://www.usgs.gov/programs/earthquake-hazards/seismographs-keeping-track-earthquakes",
        access: "Free public U.S. government educational resource",
      },
      {
        id: "sr_depth",
        title: "H/V Ambient-Noise Seismic Method",
        source: "U.S. Geological Survey",
        url: "https://water.usgs.gov/ogw/bgas/hvseismic/",
        access: "Free public U.S. government technical resource",
      },
      {
        id: "sr_dispersion",
        title: "Dispersion of Rayleigh Waves in the Frequency Domain",
        source: "U.S. Geological Survey",
        url: "https://pubs.usgs.gov/publication/ofr20201065",
        access: "Free public U.S. government report",
      },
      {
        id: "sr_coherence",
        title: "Coherence",
        source: "SciPy documentation",
        url: "https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.coherence.html",
        access: "Free open-source documentation · BSD-3-Clause",
      },
      {
        id: "sr_multiphysics",
        title: "Geophysical Methods and Applications",
        source: "U.S. Geological Survey",
        url: "https://water.usgs.gov/ogw/gwrp/activities/geophysical_methods.html",
        access: "Free public U.S. government technical resource",
      },
    ],
    equation: "A(f) ∝ 1 / √[(f₀² − f²)² + (2ζf₀f)²]",
    equationGuide: "Response depends on natural frequency f₀ and damping ratio ζ; higher damping broadens and lowers the peak.",
    equationReadingId: "sr_forced",
    predictionPrompt: "If damping increases, how should a narrow resonance peak change?",
    predictionOptions: ["It broadens and lowers", "It sharpens and grows", "It moves to infinite frequency"],
    misconception: "A peak shared by several stations must originate underground.",
    correction: "Shared infrastructure, weather, processing, or synchronization can also create coherent peaks.",
    sourceUses: ["USGS regional events", "NWS pressure", "Station geometry and timing"],
    withholdingLabel: "Withhold station 04",
  },
  quantum_state_institute: {
    code: "QS-06",
    title: "State estimation and information laboratory",
    discipline: "Probability · basis choice · tomography · entropy · decoherence",
    controls: [
      {
        id: "priorWeight",
        readingId: "qs_tomography",
        label: "Prior weight",
        minimum: 0,
        maximum: 100,
        step: 1,
        unit: "%",
        initial: 35,
        teaches: "An estimate can depend on assumptions made before the latest measurements are considered.",
      },
      {
        id: "basisAngle",
        readingId: "qs_measurement",
        label: "Measurement-basis angle",
        minimum: 0,
        maximum: 180,
        step: 2,
        unit: "°",
        initial: 46,
        teaches: "The probability distribution changes with the measurement basis.",
      },
      {
        id: "decoherence",
        readingId: "qs_dephasing",
        label: "Dephasing strength",
        minimum: 0,
        maximum: 100,
        step: 1,
        unit: "%",
        initial: 18,
        teaches: "Dephasing suppresses off-diagonal coherence without simply deleting probability.",
      },
      {
        id: "shotCount",
        readingId: "qs_sampling",
        label: "Measurement shots",
        minimum: 32,
        maximum: 4_096,
        step: 32,
        unit: "",
        initial: 512,
        teaches: "Finite-sample uncertainty shrinks approximately with one over the square root of the shot count.",
      },
      {
        id: "calibrationError",
        readingId: "qs_calibration",
        label: "Basis calibration error",
        minimum: -15,
        maximum: 15,
        step: 0.5,
        unit: "°",
        initial: 0,
        teaches: "A systematic basis rotation is not removed by collecting more shots.",
      },
    ],
    tools: [
      { id: "bloch", label: "State manifold", focus: "Relate basis angle to a two-state vector representation." },
      { id: "density", label: "Density matrix", focus: "Inspect populations, coherence, purity, and entropy." },
      { id: "sensitivity", label: "Basis sensitivity", focus: "Compare estimates over alternate measurement bases." },
    ],
    concepts: [
      { title: "Measurement basis", explanation: "A basis defines which alternatives a measurement distinguishes.", readingId: "qs_measurement" },
      { title: "Density matrix", explanation: "Diagonal terms are populations; off-diagonal terms encode coherence.", readingId: "qs_density" },
      { title: "Purity and entropy", explanation: "These quantify how concentrated or mixed a state estimate is.", readingId: "qs_measures" },
      { title: "Tomography and priors", explanation: "State reconstruction combines measurements, calibration, likelihoods, and declared assumptions.", readingId: "qs_tomography" },
    ],
    readings: [
      {
        id: "qs_measurement",
        title: "Formulations of Quantum Measurements",
        source: "IBM Quantum Learning",
        url: "https://quantum.cloud.ibm.com/learning/en/courses/general-formulation-of-quantum-information/general-measurements/formulations-of-measurements",
        access: "Free official learning module",
      },
      {
        id: "qs_density",
        title: "Density Matrix Basics",
        source: "IBM Quantum Learning",
        url: "https://quantum.cloud.ibm.com/learning/en/courses/general-formulation-of-quantum-information/density-matrices/density-matrix-basics",
        access: "Free official learning module",
      },
      {
        id: "qs_dephasing",
        title: "Quantum Channel Basics",
        source: "IBM Quantum Learning",
        url: "https://quantum.cloud.ibm.com/learning/en/courses/general-formulation-of-quantum-information/quantum-channels/quantum-channel-basics",
        access: "Free official learning module",
      },
      {
        id: "qs_tomography",
        title: "State Tomography",
        source: "Qiskit Experiments documentation",
        url: "https://qiskit-community.github.io/qiskit-experiments/stubs/qiskit_experiments.library.tomography.StateTomography.html",
        access: "Free open-source documentation · Apache-2.0",
      },
      {
        id: "qs_sampling",
        title: "A Population Proportion",
        source: "OpenStax Introductory Statistics",
        url: "https://openstax.org/books/introductory-statistics-2e/pages/8-3-a-population-proportion",
        access: "Free textbook · CC BY-NC-SA 4.0",
      },
      {
        id: "qs_measures",
        title: "Quantum Information",
        source: "IBM Quantum documentation",
        url: "https://quantum.cloud.ibm.com/docs/en/api/qiskit/quantum_info",
        access: "Free official API documentation",
      },
      {
        id: "qs_calibration",
        title: "QPU Information",
        source: "IBM Quantum documentation",
        url: "https://quantum.cloud.ibm.com/docs/en/guides/qpu-information",
        access: "Free official technical guide",
      },
    ],
    equation: "ρ = [[p, c], [c*, 1 − p]]",
    equationGuide: "The density matrix ρ separates populations p from coherence c; valid eigenvalues are non-negative and sum to one.",
    equationReadingId: "qs_density",
    predictionPrompt: "If dephasing increases while populations remain fixed, what should happen to off-diagonal coherence?",
    predictionOptions: ["It decreases", "It increases without bound", "It becomes a new population"],
    misconception: "Using a density matrix proves that the underlying phenomenon is quantum.",
    correction: "Density matrices are mathematical state descriptions. The representation alone does not establish physical ontology.",
    sourceUses: ["Cross-facility timing", "NOAA SWPC magnetic activity", "Calibration and basis metadata"],
    withholdingLabel: "Withhold the observer basis",
  },
};

export function initialScienceControls(
  facilityId: EnvironmentalFacilityId,
): ScienceControlValues {
  return Object.fromEntries(
    FACILITY_SCIENCE[facilityId].controls.map((control) => [
      control.id,
      control.initial,
    ]),
  );
}

function value(
  controls: ScienceControlValues,
  id: string,
  fallback: number,
): number {
  const candidate = controls[id];
  return Number.isFinite(candidate) ? candidate : fallback;
}

function clamp(candidate: number, minimum = 0, maximum = 1): number {
  return Math.min(maximum, Math.max(minimum, candidate));
}

function rms(values: readonly number[]): number {
  if (values.length === 0) return 0;
  return Math.sqrt(
    values.reduce((total, candidate) => total + candidate * candidate, 0) /
      values.length,
  );
}

function mean(values: readonly number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((total, candidate) => total + candidate, 0) / values.length;
}

function correlation(left: readonly number[], right: readonly number[]): number {
  const length = Math.min(left.length, right.length);
  if (length === 0) return 0;
  const leftMean = mean(left.slice(0, length));
  const rightMean = mean(right.slice(0, length));
  let numerator = 0;
  let leftPower = 0;
  let rightPower = 0;
  for (let index = 0; index < length; index += 1) {
    const a = left[index] - leftMean;
    const b = right[index] - rightMean;
    numerator += a * b;
    leftPower += a * a;
    rightPower += b * b;
  }
  return numerator / Math.max(0.000001, Math.sqrt(leftPower * rightPower));
}

function spectrum(samples: readonly number[], bins: number): number[] {
  return Array.from({ length: bins }, (_, bin) => {
    let real = 0;
    let imaginary = 0;
    for (let index = 0; index < samples.length; index += 1) {
      const angle = (2 * Math.PI * bin * index) / samples.length;
      real += samples[index] * Math.cos(angle);
      imaginary -= samples[index] * Math.sin(angle);
    }
    return Math.hypot(real, imaginary) / Math.max(1, samples.length);
  });
}

function circularInterpolate(
  samples: readonly number[],
  index: number,
): number {
  const length = samples.length;
  if (length === 0) return 0;
  const wrapped = ((index % length) + length) % length;
  const lower = Math.floor(wrapped);
  const upper = (lower + 1) % length;
  const fraction = wrapped - lower;
  return samples[lower] * (1 - fraction) + samples[upper] * fraction;
}

function distanceKilometers(
  leftLatitude: number,
  leftLongitude: number,
  rightLatitude: number,
  rightLongitude: number,
): number {
  const radians = Math.PI / 180;
  const deltaLatitude = (rightLatitude - leftLatitude) * radians;
  const deltaLongitude = (rightLongitude - leftLongitude) * radians;
  const left = leftLatitude * radians;
  const right = rightLatitude * radians;
  const haversine =
    Math.sin(deltaLatitude / 2) ** 2 +
    Math.cos(left) * Math.cos(right) * Math.sin(deltaLongitude / 2) ** 2;
  return 6_371 * 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine));
}

function entropy(probabilities: readonly number[]): number {
  return -probabilities.reduce(
    (total, probability) =>
      total + (probability > 0 ? probability * Math.log2(probability) : 0),
    0,
  );
}

function nowIso(): string {
  return new Date().toISOString();
}

function facilityHeatLayer(
  facilityId: EnvironmentalFacilityId,
  label: string,
  intensities: readonly number[],
  spread = 0.22,
): PublicAnomalyMapLayer {
  const facility = ENVIRONMENTAL_FACILITIES[facilityId];
  return {
    layerId: `analysis-${facilityId}-field`,
    kind: "heatmap",
    label,
    cells: intensities.map((intensity, index) => {
      const angle = (index / Math.max(1, intensities.length)) * Math.PI * 2;
      const radius = spread * (0.45 + (index % 4) * 0.22);
      return {
        cellId: `${facilityId}-${index}`,
        latitude: facility.latitude + Math.sin(angle) * radius,
        longitude:
          facility.longitude +
          (Math.cos(angle) * radius) /
            Math.max(0.25, Math.cos((facility.latitude * Math.PI) / 180)),
        intensity: clamp(intensity),
        radiusKm: 12 + clamp(intensity) * 28,
        sourceReferences: [`workstation:${facilityId}`],
      };
    }),
  };
}

function boundaryFrame(
  controls: ScienceControlValues,
  withheld: boolean,
  tick: number,
): FacilityScienceFrame {
  const correction = value(controls, "clockCorrection", 0);
  const sampleRate = value(controls, "sampleRate", 64);
  const cutoff = value(controls, "filterCutoff", 24);
  const sealedNoise = value(controls, "noiseLevel", 18) / 100;
  const clockDrift = value(controls, "clockDrift", 0);
  const sealedPropagationStress = 0.22;
  const count = 128;
  const phase = tick * 0.08;
  const optical = Array.from({ length: count }, (_, index) => {
    const time = index / sampleRate;
    return (
      Math.sin(2 * Math.PI * 8 * time + phase) +
      0.36 * Math.sin(2 * Math.PI * 19.5 * time) +
      0.08 * Math.sin(index * 1.73 + tick * 0.17) * (1 + sealedNoise)
    );
  });
  const actualLagSamples = Math.max(1, sampleRate * 0.04);
  const rawRadio = optical.map((_, index) => {
    const driftSamples = index * clockDrift * 0.000001;
    const source = circularInterpolate(
      optical,
      index - actualLagSamples - driftSamples,
    );
    return source * (1 - sealedNoise * 0.08) +
      Math.sin(index * 0.91 + tick * 0.2) *
        sealedPropagationStress *
        (0.04 + sealedNoise * 0.3);
  });
  const correctionSamples = (correction / 1_000) * sampleRate;
  const corrected = rawRadio.map(
    (_, index) => circularInterpolate(rawRadio, index + correctionSamples),
  );
  const lagCandidates = Array.from({ length: 25 }, (_, index) => index - 12);
  const lagScores = lagCandidates.map((lag) =>
    correlation(
      optical,
      rawRadio.map(
        (_, index) =>
          rawRadio[(index + lag + rawRadio.length) % rawRadio.length],
      ),
    ),
  );
  const bestIndex = lagScores.indexOf(Math.max(...lagScores));
  const bestLag = lagCandidates[bestIndex];
  const residuals = optical.map((sample, index) => sample - corrected[index]);
  const unfilteredAmplitudes = spectrum(optical, 48);
  const amplitudes = unfilteredAmplitudes.map((amplitude, bin) => {
    const frequency = (bin * sampleRate) / count;
    return frequency <= cutoff ? amplitude : amplitude * 0.08;
  });
  const retainedSpectralEnergy =
    amplitudes.reduce((total, amplitude) => total + amplitude ** 2, 0) /
    Math.max(
      0.000001,
      unfilteredAmplitudes.reduce(
        (total, amplitude) => total + amplitude ** 2,
        0,
      ),
    );
  const residualWindows = Array.from({ length: 8 }, (_, windowIndex) => {
    const start = windowIndex * (count / 8);
    return clamp(rms(residuals.slice(start, start + count / 8)) / 1.4);
  });
  const nyquist = sampleRate / 2;
  const aliases = nyquist < 19.5;
  return {
    method: withheld
      ? "Streaming 128-sample optical waveform and direct discrete Fourier transform; radio-dependent lag and residual products withheld."
      : "Streaming 128-sample waveform; direct discrete Fourier transform; normalized lag correlation; fractional-delay residual RMS.",
    observation: withheld
      ? `With the radio return withheld, cross-channel lag and propagation residuals are not estimable. The optical sampling and spectrum remain available.`
      : aliases
        ? `The 19.5 Hz component exceeds the ${nyquist.toFixed(1)} Hz Nyquist boundary and appears at a false lower frequency.`
        : `Both injected components fall below the ${nyquist.toFixed(1)} Hz Nyquist boundary; the lag peak remains measurable.`,
    metrics: [
      {
        label: "Measured lag",
        readingId: "ba_correlation",
        value: withheld
          ? "withheld"
          : `${((bestLag / sampleRate) * 1_000).toFixed(1)} ms`,
        detail: withheld ? "radio dependency removed" : `r = ${lagScores[bestIndex].toFixed(3)}`,
      },
      {
        label: "Residual RMS",
        readingId: "ba_correlation",
        value: withheld
          ? "withheld"
          : `${(rms(residuals) * 1_000).toFixed(1)} mV`,
        detail: withheld
          ? "requires both optical and radio channels"
          : `${correction.toFixed(0)} ms fractional trial correction`,
      },
      { label: "Nyquist frequency", readingId: "ba_sampling", value: `${nyquist.toFixed(1)} Hz`, detail: aliases ? "19.5 Hz component aliases" : "both components represented" },
      { label: "End-window drift", readingId: "ba_clock_drift", value: `${((clockDrift * 0.000001 * count / sampleRate) * 1_000).toFixed(3)} ms`, detail: `${clockDrift.toFixed(0)} ppm relative rate` },
      {
        label: "Retained spectral energy",
        readingId: "ba_signals",
        value: `${(retainedSpectralEnergy * 100).toFixed(1)}%`,
        detail: `${cutoff.toFixed(0)} Hz low-pass · ${Math.round(sealedNoise * 100)}% acquisition noise`,
      },
      {
        label: "Modeled noise RMS",
        readingId: "ba_signals",
        value: `${((0.08 * (1 + sealedNoise) / Math.sqrt(2)) * 1_000).toFixed(1)} mV`,
        detail: `${Math.round(sealedNoise * 100)}% acquisition-noise setting`,
      },
    ],
    records: [
      { channel: "Optical photometry", reading: `${count} samples at ${sampleRate} Hz`, retained: true },
      { channel: "Radio return", reading: `40 ms injected delay`, retained: !withheld },
      { channel: "Low-pass analysis", reading: `${cutoff} Hz cutoff`, retained: true },
      { channel: "Acquisition noise", reading: `${Math.round(sealedNoise * 100)}% calibration level`, retained: true },
      { channel: "Clock calibration", reading: `${clockDrift.toFixed(0)} ppm relative drift`, retained: true },
    ],
    series: {
      optical,
      radio: withheld ? [] : corrected,
      spectrum: amplitudes,
      lag: withheld ? [] : lagScores,
      residual: withheld ? [] : residuals,
    },
    matrix: [],
    points: [],
    bars: amplitudes,
    mapLayers: withheld
      ? []
      : [
          facilityHeatLayer(
            "boundary_array",
            "Boundary propagation residual field",
            residualWindows.map((candidate) =>
              clamp(
                candidate * (0.55 + retainedSpectralEnergy * 0.45) +
                  sealedNoise * 0.08,
              )
            ),
            0.18 + Math.min(0.22, Math.abs(clockDrift) / 2_500),
          ),
        ],
  };
}

function aeronauticalFrame(
  controls: ScienceControlValues,
  withheld: boolean,
  tick: number,
): FacilityScienceFrame {
  const trust = value(controls, "fusionWeight", 58) / 100;
  const windCorrection = value(controls, "windCorrection", 0);
  const noise = value(controls, "measurementNoise", 6);
  const latency = value(controls, "clockLatency", 0);
  const processNoise = value(controls, "processNoise", 22) / 100;
  const recordedWind = 12;
  const count = 36;
  const primary = Array.from({ length: count }, (_, index) => {
    const time = index / 5;
    return {
      x: index * 2.8,
      y:
        16 +
        index * 1.45 +
        Math.sin(index * 0.34 + tick * 0.035) * (2.4 + processNoise * 3.2),
      group: 0,
      uncertainty: noise * 0.55,
    };
  });
  const transponder = primary.map((point, index) => ({
    x:
      point.x +
      2.1 +
      latency * 0.72 +
      Math.sin(index * 0.6) * noise * 0.12,
    y:
      point.y -
      3.6 +
      latency * 0.34 +
      Math.cos(index * 0.47) * noise * 0.16,
    group: 1,
    uncertainty: noise * 0.4 + processNoise * 2.5,
  }));
  const bearing = primary.map((point, index) => ({
    x: point.x - 3.4 + Math.sin(index * 0.29 + tick * 0.08) * noise * 0.34,
    y:
      point.y +
      4.7 +
      Math.cos(index * 0.53) * noise * 0.28 -
      (windCorrection - recordedWind * 0.54) * (index / count) * 0.09,
    group: 2,
    uncertainty: noise + processNoise * 3,
  }));
  const fused = primary.map((point, index) => ({
    x:
      point.x * (1 - trust) +
      transponder[index].x * trust * 0.68 +
      bearing[index].x * trust * 0.32,
    y:
      point.y * (1 - trust) +
      transponder[index].y * trust * 0.68 +
      bearing[index].y * trust * 0.32,
    group: 3,
    uncertainty:
      noise * Math.sqrt((1 - trust) ** 2 + trust ** 2 * 0.57) +
      processNoise * 2,
  }));
  const feedResiduals = primary.map((point, index) =>
    Math.hypot(point.x - bearing[index].x, point.y - bearing[index].y),
  );
  const fusionResiduals = fused.map((point, index) =>
    Math.hypot(point.x - primary[index].x, point.y - primary[index].y),
  );
  const speeds = fused.slice(1).map((point, index) =>
    Math.hypot(point.x - fused[index].x, point.y - fused[index].y) * 5,
  );
  const facility = ENVIRONMENTAL_FACILITIES.aeronautical_incident_center;
  const trajectory = fused.map((point, index) => ({
    sampleId: `fusion-${index}`,
    latitude: facility.latitude + (point.y - fused[0].y) * 0.012,
    longitude: facility.longitude + (point.x - fused[0].x) * 0.015,
    observedAt: nowIso(),
    uncertaintyKm: point.uncertainty,
    sourceReference: "workstation:aeronautical_incident_center",
  }));
  return {
    method:
      "Streaming kinematic tracks with weighted fusion, wind correction, propagated uncertainty, and pointwise residuals.",
    observation:
      noise > 10
        ? "The bearing envelope expands faster than the fused line changes; a smooth estimate still carries broad uncertainty."
        : "The feeds remain distinguishable. Changing trust moves the fused estimate toward one dependency rather than creating new information.",
    metrics: [
      { label: "Feed divergence", readingId: "ai_triangulation", value: `${rms(feedResiduals).toFixed(2)} km`, detail: "primary vs bearing" },
      { label: "Fusion residual", readingId: "ai_kalman", value: `${rms(fusionResiduals).toFixed(2)} km`, detail: `${Math.round(trust * 100)}% transponder trust` },
      { label: "Mean speed", readingId: "ai_motion", value: `${mean(speeds).toFixed(1)} km/h`, detail: `${windCorrection.toFixed(0)} kt applied correction` },
      { label: "95% radius", readingId: "ai_estimation", value: `${((noise + processNoise * 3) * 1.96).toFixed(1)} km`, detail: `${latency.toFixed(1)} s latency · process noise ${Math.round(processNoise * 100)}%` },
    ],
    records: [
      { channel: "Primary radar", reading: `${count} direct plots`, retained: true },
      { channel: "Transponder", reading: `${count} reported positions`, retained: true },
      { channel: "Bearing solution", reading: `σ = ${noise.toFixed(1)} km`, retained: true },
      { channel: "Fused display", reading: `${Math.round(trust * 100)}% dependency weight`, retained: !withheld },
      { channel: "Timing model", reading: `${latency.toFixed(1)} s latency`, retained: true },
    ],
    series: {
      residual: feedResiduals,
      fusionResidual: fusionResiduals,
      speed: speeds,
    },
    matrix: [],
    points: withheld
      ? [...primary, ...transponder, ...bearing]
      : [...primary, ...transponder, ...bearing, ...fused],
    bars: primary.slice(0, 12).map((_, index) => noise * (0.6 + index / 20)),
    mapLayers: withheld
      ? []
      : [
          {
            layerId: "analysis-aeronautical-fused-track",
            kind: "trajectory",
            label: "Current fused trajectory",
            samples: trajectory,
          },
          facilityHeatLayer(
            "aeronautical_incident_center",
            "Current trajectory uncertainty",
            Array.from({ length: 10 }, (_, index) =>
              clamp((noise / 20) * (0.55 + index / 20)),
            ),
            0.45,
          ),
        ],
  };
}

interface ArchiveCase {
  id: string;
  year: number;
  parent: string | null;
  vector: [number, number, number];
  latitude: number;
  longitude: number;
}

const ARCHIVE_CASES: readonly ArchiveCase[] = Array.from(
  { length: 30 },
  (_, index) => {
    const root = index % 5 === 2 ? Math.max(0, index - 2) : null;
    const family = index % 6;
    return {
      id: `A${String(index + 1).padStart(2, "0")}`,
      year: 1945 + index * 2 + (index % 3),
      parent: root === null ? null : `A${String(root + 1).padStart(2, "0")}`,
      vector: [
        clamp(0.18 + family * 0.12 + Math.sin(index * 0.7) * 0.06),
        clamp(0.84 - family * 0.09 + Math.cos(index * 0.43) * 0.07),
        clamp(0.25 + (index % 4) * 0.18 + Math.sin(index * 0.21) * 0.08),
      ],
      latitude: 28 + ((index * 17) % 20),
      longitude: -123 + ((index * 29) % 47),
    };
  },
);

function archiveFrame(
  controls: ScienceControlValues,
  withheld: boolean,
  tick: number,
): FacilityScienceFrame {
  const threshold = value(controls, "similarityThreshold", 72) / 100;
  const timeWindow = value(controls, "timeWindow", 35);
  const provenanceWeight = value(controls, "provenanceWeight", 70) / 100;
  const geographicRadius = value(controls, "geographicRadius", 1_200);
  const exposureNormalization =
    value(controls, "exposureNormalization", 60) / 100;
  const latestYear = 2005;
  const archiveSite = ENVIRONMENTAL_FACILITIES.aerial_phenomena_archive;
  const inWindow = ARCHIVE_CASES.filter((item) =>
    item.year >= latestYear - timeWindow &&
    distanceKilometers(
      archiveSite.latitude,
      archiveSite.longitude,
      item.latitude,
      item.longitude,
    ) <= geographicRadius
  );
  const active = withheld
    ? inWindow.filter((item) => item.parent === null)
    : inWindow;
  const similarities = active.map((left) =>
    active.map((right) => {
      const distance = Math.sqrt(
        left.vector.reduce(
          (sum, component, index) =>
            sum + (component - right.vector[index]) ** 2,
          0,
        ),
      );
      const base = 1 - distance / Math.sqrt(3);
      const dependentParticipants =
        left.id === right.id
          ? 0
          : Number(left.parent !== null) + Number(right.parent !== null);
      const directDependency =
        left.parent === right.id || right.parent === left.id;
      const dependencePenalty =
        provenanceWeight *
        (dependentParticipants * 0.07 + (directDependency ? 0.21 : 0));
      return clamp(base - dependencePenalty);
    }),
  );
  let links = 0;
  similarities.forEach((row, left) =>
    row.forEach((similarity, right) => {
      if (right > left && similarity >= threshold) links += 1;
    }),
  );
  const chronology = Array.from({ length: 12 }, (_, bin) => {
    const start = latestYear - timeWindow + (bin * timeWindow) / 12;
    const end = latestYear - timeWindow + ((bin + 1) * timeWindow) / 12;
    const count = active.filter(
      (item) => item.year >= start && item.year < end,
    ).length;
    const exposure = 0.65 + bin / 18;
    return count * (1 - exposureNormalization) +
      (count / exposure) * exposureNormalization;
  });
  const roots = active.filter((item) => item.parent === null).length;
  const normalizedEventRate = mean(chronology);
  const retainedDependencyEdges = active.filter(
    (item) =>
      item.parent !== null &&
      active.some((candidate) => candidate.id === item.parent),
  ).length;
  const documentedDescendants = active.filter(
    (item) => item.parent !== null,
  ).length;
  const appliedDependencePenalty =
    provenanceWeight *
    (documentedDescendants * 0.07 + retainedDependencyEdges * 0.21);
  const expectedChanceLinks =
    (active.length *
      Math.max(0, active.length - 1) *
      (1 - threshold) ** 2 *
      (geographicRadius / 1_200)) /
    2;
  const points = active.map((item, index) => ({
    x: ((item.year - (latestYear - timeWindow)) / timeWindow) * 100,
    y: item.vector[0] * 70 + Math.sin(index + tick * 0.02) * 1.2,
    group: item.parent ? 1 : 0,
    uncertainty: 2,
  }));
  return {
    method:
      "Weighted Euclidean feature distance with temporal filtering, explicit source-dependence penalty, chronology bins, and chance-match baseline.",
    observation: withheld
      ? `Removing copy descendants leaves ${roots} independent roots and ${links} above-threshold links.`
      : `The current threshold produces ${links} links, including records whose source ancestry must be inspected before recurrence is inferred.`,
    metrics: [
      { label: "Records retained", readingId: "ap_sampling", value: String(active.length), detail: `${timeWindow.toFixed(0)}-year comparison window` },
      { label: "Independent roots", readingId: "ap_provenance", value: String(roots), detail: `${Math.round(provenanceWeight * 100)}% provenance weight` },
      { label: "Recurrence links", readingId: "ap_clustering", value: String(links), detail: `similarity ≥ ${Math.round(threshold * 100)}%` },
      { label: "Chance baseline", readingId: "ap_probability", value: expectedChanceLinks.toFixed(1), detail: `${geographicRadius.toFixed(0)} km radius · ${Math.round(exposureNormalization * 100)}% exposure correction` },
      {
        label: "Exposure-normalized rate",
        readingId: "ap_sampling",
        value: normalizedEventRate.toFixed(2),
        detail: `mean records per chronology bin at ${Math.round(exposureNormalization * 100)}% correction`,
      },
      {
        label: "Dependence penalty",
        readingId: "ap_provenance",
        value: appliedDependencePenalty.toFixed(3),
        detail: `${documentedDescendants} documented descendants · ${retainedDependencyEdges} retained parent-child edges · ${Math.round(provenanceWeight * 100)}% weight`,
      },
    ],
    records: ARCHIVE_CASES.map((item) => ({
      channel: item.id,
      reading: `${item.year} · ${item.parent ? `descends from ${item.parent}` : "independent root"}`,
      retained: active.includes(item),
    })),
    series: { chronology },
    matrix: similarities,
    points,
    bars: chronology,
    mapLayers: [
      {
        layerId: "analysis-archive-recurrence",
        kind: "heatmap",
        label: "Filtered archive recurrence field",
        cells: active.map((item, index) => ({
          cellId: item.id,
          latitude: item.latitude,
          longitude: item.longitude,
          intensity: (() => {
            const scores =
              similarities[index]?.filter((_, other) => other !== index) ?? [];
            const linkFraction =
              scores.filter((score) => score >= threshold).length /
              Math.max(1, scores.length);
            const chronologyPosition = clamp(
              (item.year - (latestYear - timeWindow)) /
                Math.max(1, timeWindow),
            );
            const exposure = 0.65 + (chronologyPosition * 11) / 18;
            const exposureFactor =
              1 - exposureNormalization +
              exposureNormalization / Math.max(0.25, exposure);
            return clamp(
              mean(scores) *
                (0.45 + linkFraction * 0.55) *
                exposureFactor,
            );
          })(),
          radiusKm: 35 + (similarities[index]?.filter((score) => score >= threshold).length ?? 0) * 8,
          sourceReferences: [`archive:${item.id}`],
        })),
      },
    ],
  };
}

function holographyFrame(
  controls: ScienceControlValues,
  withheld: boolean,
  tick: number,
): FacilityScienceFrame {
  const coverage = value(controls, "angularCoverage", 78) / 100;
  const phase = (value(controls, "phaseOffset", 0) * Math.PI) / 180;
  const regularization = value(controls, "regularization", 35) / 100;
  const projectionCount = Math.max(
    8,
    Math.round(value(controls, "projectionCount", 32)),
  );
  const phaseNoise = value(controls, "phaseNoise", 12) / 100;
  const recordedAttenuation = 0.15;
  const size = 20;
  const displayAngles = 16;
  const detectorCount = 24;
  const availableViews = Math.max(1, Math.round(projectionCount * coverage));
  const withheldViews = withheld ? Math.ceil(availableViews / 3) : 0;
  const views = Math.max(1, availableViews - withheldViews);
  const samplingUncertainty = 1 / Math.sqrt(views);
  const heldoutDisplayStart = Math.ceil((displayAngles * 2) / 3);
  const sinogram = Array.from({ length: displayAngles }, (_, angleIndex) =>
    Array.from({ length: detectorCount }, (_, detector) => {
      if (withheld && angleIndex >= heldoutDisplayStart) return 0;
      const normalizedAngle = angleIndex / Math.max(1, displayAngles - 1);
      const requestedIndex = Math.round(
        normalizedAngle * Math.max(1, projectionCount - 1),
      );
      const angle =
        (requestedIndex / Math.max(1, projectionCount - 1)) *
        Math.PI *
        coverage;
      const idealAngle = normalizedAngle * Math.PI * coverage;
      const angularQuantization = Math.abs(angle - idealAngle) / Math.PI;
      const coordinate = detector / Math.max(1, detectorCount - 1) - 0.5;
      const primary = Math.exp(
        -((coordinate - Math.sin(angle + phase) * 0.18) ** 2) / 0.025,
      );
      const secondary =
        0.68 *
        Math.exp(
          -((coordinate + Math.cos(angle * 1.3 - phase) * 0.24) ** 2) /
            0.045,
        );
      return clamp(
        (primary + secondary) *
          (1 - recordedAttenuation * 0.12) +
          Math.sin(
            detector * 0.8 +
              tick * 0.06 +
              angleIndex * 0.31,
          ) *
            (0.006 +
              phaseNoise * 0.12 +
              samplingUncertainty * 0.035 +
              angularQuantization * 0.6),
      );
    }),
  );
  const effectiveCoverage = clamp(
    coverage * (withheld ? 2 / 3 : 1),
    0.05,
    1,
  );
  const unregularized = Array.from({ length: size }, (_, row) =>
    Array.from({ length: size }, (_, column) => {
      const x = column / (size - 1) - 0.5;
      const y = row / (size - 1) - 0.5;
      const phantom =
        Math.exp(-((x - 0.13) ** 2 + (y + 0.08) ** 2) / 0.035) +
        0.72 * Math.exp(-((x + 0.2) ** 2 + (y - 0.17) ** 2) / 0.06);
      const limitedAngle =
        Math.sin(
          (x * 8 + y * 3) / Math.max(0.18, effectiveCoverage) + phase,
        ) *
        ((1 - effectiveCoverage) * 0.42 + samplingUncertainty * 0.12);
      const acquisitionNoise =
        Math.sin(
          row * 1.37 +
            column * 0.83 +
            tick * 0.04 +
            projectionCount * 0.07,
        ) *
        phaseNoise *
        (0.025 + samplingUncertainty * 0.08);
      return phantom + limitedAngle + acquisitionNoise;
    }),
  );
  const smoothing = regularization * 0.18;
  const regularized = unregularized.map((row) =>
    row.map((candidate) =>
      candidate * (1 - smoothing) + smoothing * 0.36
    )
  );
  const reconstruction = regularized.map((row) =>
    row.map((candidate) => clamp(candidate))
  );
  const regularizationBias = mean(
    regularized.flatMap((row, rowIndex) =>
      row.map((candidate, columnIndex) =>
        Math.abs(candidate - unregularized[rowIndex][columnIndex])
      )
    ),
  );
  const phaseNoiseRms =
    phaseNoise * (0.025 + samplingUncertainty * 0.08) / Math.sqrt(2);
  const residual = Array.from({ length: 32 }, (_, index) => {
    const angle = index / 31;
    const heldoutFamily =
      withheld &&
      angle <= coverage &&
      angle >= coverage * (2 / 3);
    const missing =
      angle > coverage
        ? 0.36 + (angle - coverage) * 0.8
        : heldoutFamily
          ? 0.24 + (angle - coverage * (2 / 3)) * 0.35
          : 0.04;
    return (
      missing +
      samplingUncertainty * 0.09 +
      Math.abs(Math.sin(index * 0.43 + phase)) *
        (1 - regularization) *
        (0.04 + phaseNoise * 0.16)
    );
  });
  const meanResidual = mean(residual);
  const support = reconstruction.flat().filter((candidate) => candidate > 0.5).length /
    (size * size);
  return {
    method:
      "Synthetic line-integral projection set, limited-angle inverse reconstruction, regularization bias, and withheld-angle residual.",
    observation:
      withheld
        ? "Projection family C is absent from the reconstruction. Its angles remain only as a holdout test, increasing directional artifacts and prediction residuals."
        : coverage < 0.55
          ? "The reconstruction develops directional streaks: the missing angles are being supplied by assumptions rather than measurements."
          : "Broad angular coverage stabilizes both bright regions, while regularization still changes edge sharpness and support.",
    metrics: [
      {
        label: "Active projections",
        readingId: "hl_radon",
        value: `${views} / ${projectionCount}`,
        detail: `${Math.round(coverage * 100)}% scheduled coverage${withheld ? " · family C withheld" : ""}`,
      },
      { label: "Mean residual", readingId: "hl_inverse", value: meanResidual.toFixed(4), detail: withheld ? "family withheld" : "all families retained" },
      { label: "Supported cells", readingId: "hl_radon", value: `${Math.round(support * 100)}%`, detail: "reconstruction above 0.5" },
      {
        label: "Registration phase",
        readingId: "hl_holography",
        value: `${((phase * 180) / Math.PI).toFixed(0)}°`,
        detail: `${Math.round(phaseNoise * 100)}% phase noise`,
      },
      {
        label: "Regularization bias",
        readingId: "hl_inverse",
        value: regularizationBias.toFixed(4),
        detail: `${Math.round(regularization * 100)}% strength · sampling uncertainty ${samplingUncertainty.toFixed(3)}`,
      },
      {
        label: "Phase-noise RMS",
        readingId: "hl_holography",
        value: phaseNoiseRms.toFixed(4),
        detail: `${Math.round(phaseNoise * 100)}% phase-noise setting`,
      },
    ],
    records: [
      { channel: "Projection family A", reading: "0°–60°", retained: true },
      { channel: "Projection family B", reading: "60°–120°", retained: true },
      { channel: "Projection family C", reading: "120°–180°", retained: !withheld },
      { channel: "Registration solution", reading: `${((phase * 180) / Math.PI).toFixed(0)}° phase`, retained: true },
      { channel: "Projection schedule", reading: `${projectionCount.toFixed(0)} requested angles`, retained: true },
    ],
    series: { residual },
    matrix: reconstruction,
    points: sinogram.flatMap((row, y) =>
      row.map((intensity, x) => ({ x, y, group: 0, uncertainty: intensity })),
    ),
    bars: sinogram.map((row) => mean(row)),
    mapLayers: [
      facilityHeatLayer(
        "holography_laboratory",
        "Projection-constrained reconstruction support",
        sinogram.map((row, index) =>
          withheld && index >= heldoutDisplayStart
            ? 0
            : clamp(
                mean(row) *
                  (0.55 + coverage * 0.25) *
                  (1 - samplingUncertainty * 0.35) *
                  (1 - regularization * 0.18),
              ),
        ),
        0.16 + coverage * 0.28,
      ),
    ],
  };
}

function subsurfaceFrame(
  controls: ScienceControlValues,
  withheld: boolean,
  tick: number,
): FacilityScienceFrame {
  const trial = value(controls, "trialFrequency", 8.5);
  const velocity = value(controls, "waveVelocity", 4.8);
  const damping = value(controls, "damping", 24) / 100;
  const maximumDepth = value(controls, "depthRange", 18);
  const coherenceWindow = value(controls, "coherenceWindow", 8);
  const recordedBackground = 0.12;
  const depths = Array.from(
    { length: 24 },
    (_, index) => 0.5 + (index / 23) * (maximumDepth - 0.5),
  );
  const frequencies = Array.from(
    { length: 32 },
    (_, index) => 1 + (index / 31) * 23,
  );
  const field = depths.map((depth) =>
    frequencies.map((frequency) => {
      const fundamental = 2.4 + (depth / velocity) * 2.2;
      const secondary = 18 - depth * 0.31;
      const width = 0.35 + damping * 3.2;
      const first =
        1 / (1 + ((frequency - fundamental) / width) ** 2);
      const second =
        0.55 / (1 + ((frequency - secondary) / (width * 1.4)) ** 2);
      return clamp(
        (first + second) *
          (0.86 + recordedBackground * 0.12) +
          Math.sin(depth * 0.7 + frequency + tick * 0.05) *
            (0.008 + 0.03 / Math.sqrt(coherenceWindow)),
      );
    }),
  );
  const frequencyStep = frequencies[1] - frequencies[0];
  const trialPosition = clamp(
    (trial - frequencies[0]) / frequencyStep,
    0,
    frequencies.length - 1,
  );
  const lowerTrialIndex = Math.floor(trialPosition);
  const upperTrialIndex = Math.min(
    frequencies.length - 1,
    lowerTrialIndex + 1,
  );
  const trialFraction = trialPosition - lowerTrialIndex;
  const depthResponse = field.map(
    (row) =>
      row[lowerTrialIndex] * (1 - trialFraction) +
      row[upperTrialIndex] * trialFraction,
  );
  const interpolatedFrequency =
    frequencies[lowerTrialIndex] * (1 - trialFraction) +
    frequencies[upperTrialIndex] * trialFraction;
  const peakDepthIndex = depthResponse.indexOf(Math.max(...depthResponse));
  const spectrumValues = frequencies.map((_, column) =>
    mean(field.map((row) => row[column])),
  );
  const stationEntries = [0.93, 0.88, 0.79, 0.84, 0.74].map(
    (base, index) => {
      const responseIndex = Math.round(
        (index / 4) * Math.max(0, depthResponse.length - 1),
      );
      const localModeResponse = depthResponse[responseIndex] ?? 0;
      return {
        index,
        coherence: clamp(
          (base - damping * (0.08 + index * 0.02)) *
            (0.72 + localModeResponse * 0.28) +
            Math.sin(tick * 0.04 + index) *
              (0.03 / Math.sqrt(coherenceWindow)),
        ),
      };
    },
  );
  const retainedStations = withheld
    ? stationEntries.filter((station) => station.index !== 3)
    : stationEntries;
  const stationValues = stationEntries.map((station) => station.coherence);
  const retainedValues = retainedStations.map((station) => station.coherence);
  const peakResponse = Math.max(...depthResponse);
  const stationFacility =
    ENVIRONMENTAL_FACILITIES.subsurface_resonance_station;
  const stationMapLayer: PublicAnomalyMapLayer = {
    layerId: "analysis-subsurface-station-field",
    kind: "heatmap",
    label: "Retained station modal response",
    cells: retainedStations.map((station) => {
      const angle = (station.index / stationEntries.length) * Math.PI * 2;
      const radius = 0.23 + (station.index % 2) * 0.12;
      return {
        cellId: `subsurface-station-${station.index + 1}`,
        latitude: stationFacility.latitude + Math.sin(angle) * radius,
        longitude:
          stationFacility.longitude +
          (Math.cos(angle) * radius) /
            Math.max(
              0.25,
              Math.cos((stationFacility.latitude * Math.PI) / 180),
            ),
        intensity: clamp(
          station.coherence *
            (0.45 + peakResponse * 0.4) *
            (0.9 + interpolatedFrequency / 240),
        ),
        radiusKm:
          12 +
          depths[peakDepthIndex] * 0.8 +
          maximumDepth * 0.25,
        sourceReferences: [
          `workstation:subsurface_resonance_station:station-${station.index + 1}`,
        ],
      };
    }),
  };
  return {
    method:
      "Damped modal response across a depth-frequency grid, velocity-model conversion, and network coherence withholding.",
    observation:
      damping > 0.55
        ? "High damping spreads energy across frequency and lowers the peak, making a single resonant frequency difficult to identify."
        : "Narrow modal ridges remain visible; changing velocity shifts the depth inferred from the same frequency response.",
    metrics: [
      { label: "Peak depth", readingId: "sr_depth", value: `${depths[peakDepthIndex].toFixed(1)} km`, detail: `${trial.toFixed(1)} Hz trial` },
      { label: "Network coherence", readingId: "sr_coherence", value: mean(retainedValues).toFixed(3), detail: `${retainedValues.length} stations retained` },
      { label: "Peak response", readingId: "sr_forced", value: peakResponse.toFixed(3), detail: `${Math.round(damping * 100)}% damping` },
      { label: "Velocity model", readingId: "sr_seismographs", value: `${velocity.toFixed(1)} km/s`, detail: `${maximumDepth.toFixed(0)} km range · ${coherenceWindow.toFixed(0)} s window` },
      {
        label: "Interpolated frequency",
        readingId: "sr_coherence",
        value: `${interpolatedFrequency.toFixed(2)} Hz`,
        detail: `${(1 / coherenceWindow).toFixed(3)} Hz window resolution`,
      },
      {
        label: "Modeled depth span",
        readingId: "sr_depth",
        value: `${maximumDepth.toFixed(1)} km`,
        detail: `${(1 / coherenceWindow).toFixed(3)} Hz resolution from a ${coherenceWindow.toFixed(0)} s window`,
      },
    ],
    records: stationValues.map((coherence, index) => ({
      channel: `Station ${String(index + 1).padStart(2, "0")}`,
      reading: `coherence ${coherence.toFixed(3)}`,
      retained: !withheld || index !== 3,
    })),
    series: {
      depthResponse,
      spectrum: spectrumValues,
      stations: retainedValues,
    },
    matrix: field,
    points: retainedStations.map((station) => ({
      x: station.index,
      y: station.coherence,
      group: station.index === 3 ? 1 : 0,
      uncertainty: damping * 0.2,
    })),
    bars: retainedValues,
    mapLayers: [stationMapLayer],
  };
}

function quantumFrame(
  controls: ScienceControlValues,
  withheld: boolean,
  tick: number,
): FacilityScienceFrame {
  const prior = value(controls, "priorWeight", 35) / 100;
  const requestedAngle = value(controls, "basisAngle", 46);
  const calibrationError = value(controls, "calibrationError", 0);
  const angle = ((requestedAngle + calibrationError) * Math.PI) / 180;
  const dephasing = value(controls, "decoherence", 18) / 100;
  const shots = value(controls, "shotCount", 512);
  const z = clamp(0.12 + prior * 0.68, -0.98, 0.98);
  const populationA = (1 + z) / 2;
  const populationB = 1 - populationA;
  const maximumCoherence = Math.sqrt(populationA * populationB);
  const coherence =
    maximumCoherence *
    (1 - dephasing) *
    (withheld ? 0.72 : 1);
  const real = coherence * Math.cos(angle);
  const imaginary = coherence * Math.sin(angle);
  const determinant =
    populationA * populationB - (real * real + imaginary * imaginary);
  const discriminant = Math.sqrt(Math.max(0, 1 - 4 * determinant));
  const eigenvalues = [(1 + discriminant) / 2, (1 - discriminant) / 2];
  const purity =
    populationA ** 2 +
    populationB ** 2 +
    2 * (real ** 2 + imaginary ** 2);
  const samplingError = Math.sqrt(populationA * populationB / shots);
  const basisSweep = Array.from({ length: 48 }, (_, index) => {
    const theta = (index / 47) * Math.PI;
    const predicted = clamp(
      populationA * Math.cos(theta / 2) ** 2 +
        populationB * Math.sin(theta / 2) ** 2 +
        real * Math.sin(theta),
    );
    const standardError = Math.sqrt(
      Math.max(0.000001, predicted * (1 - predicted)) / shots,
    );
    return clamp(predicted + Math.sin(tick * 0.03 + index) * standardError);
  });
  const matrix = [
    [populationA, Math.hypot(real, imaginary)],
    [Math.hypot(real, imaginary), populationB],
  ];
  const facilitySequence: EnvironmentalFacilityId[] = [
    "boundary_array",
    "aeronautical_incident_center",
    "aerial_phenomena_archive",
    "holography_laboratory",
    "subsurface_resonance_station",
    "quantum_state_institute",
  ];
  return {
    method:
      "Two-state density estimate with complex coherence, analytical eigenvalues, purity, entropy, and full basis sweep.",
    observation:
      dephasing > 0.55
        ? "Off-diagonal coherence is strongly suppressed while diagonal populations remain normalized."
        : "Rotating the basis changes predicted outcome probabilities without changing the trace of the density matrix.",
    metrics: [
      { label: "State purity", readingId: "qs_measures", value: purity.toFixed(4), detail: "Tr(ρ²)" },
      { label: "Von Neumann entropy", readingId: "qs_measures", value: `${entropy(eigenvalues).toFixed(4)} bit`, detail: "−Tr(ρ log₂ρ)" },
      { label: "Coherence magnitude", readingId: "qs_dephasing", value: Math.hypot(real, imaginary).toFixed(4), detail: `${Math.round(dephasing * 100)}% dephasing` },
      { label: "Sampling error", readingId: "qs_sampling", value: `±${samplingError.toFixed(4)}`, detail: `${shots.toFixed(0)} shots · ${calibrationError.toFixed(1)}° calibration error` },
      {
        label: "Effective basis angle",
        readingId: "qs_measurement",
        value: `${((angle * 180) / Math.PI).toFixed(1)}°`,
        detail: `${requestedAngle.toFixed(1)}° requested + ${calibrationError.toFixed(1)}° calibration`,
      },
    ],
    records: [
      { channel: "Preparation basis", reading: `prior ${(1 - prior).toFixed(2)}`, retained: true },
      { channel: "Instrument basis", reading: `${((angle * 180) / Math.PI).toFixed(0)}° rotation`, retained: true },
      { channel: "Observer basis", reading: `|c| ${Math.hypot(real, imaginary).toFixed(3)}`, retained: !withheld },
      { channel: "ρ diagonal", reading: `${populationA.toFixed(3)}, ${populationB.toFixed(3)}`, retained: true },
      { channel: "Finite sampling", reading: `${shots.toFixed(0)} measurement shots`, retained: true },
    ],
    series: { sensitivity: basisSweep },
    matrix,
    points: [
      {
        x: clamp(2 * real, -1, 1),
        y: z,
        group: 0,
        uncertainty: clamp(
          dephasing +
            samplingError * 2 +
            Math.abs(calibrationError) / 180,
        ),
      },
    ],
    bars: eigenvalues,
    mapLayers: [
      {
        layerId: "analysis-quantum-timing-network",
        kind: "trajectory",
        label: "Cross-facility basis timing path",
        samples: facilitySequence.map((facilityId, index) => {
          const facility = ENVIRONMENTAL_FACILITIES[facilityId];
          return {
            sampleId: `basis-${facilityId}`,
            latitude: facility.latitude,
            longitude: facility.longitude,
            observedAt: nowIso(),
            uncertaintyKm: 8 + dephasing * 35 + index,
            sourceReference: `workstation:${facilityId}`,
          };
        }),
      },
      facilityHeatLayer(
        "quantum_state_institute",
        "Observer-basis sampling sensitivity",
        basisSweep
          .filter((_, index) => index % 6 === 0)
          .map((probability) =>
            clamp(
              Math.abs(probability - 0.5) * 1.45 +
                samplingError * 4 +
                dephasing * 0.12,
            )
          ),
        0.17 + dephasing * 0.25,
      ),
    ],
  };
}

export function analyzeFacilityScience(
  facilityId: EnvironmentalFacilityId,
  controls: ScienceControlValues,
  withheld: boolean,
  tick: number,
): FacilityScienceFrame {
  switch (facilityId) {
    case "boundary_array":
      return boundaryFrame(controls, withheld, tick);
    case "aeronautical_incident_center":
      return aeronauticalFrame(controls, withheld, tick);
    case "aerial_phenomena_archive":
      return archiveFrame(controls, withheld, tick);
    case "holography_laboratory":
      return holographyFrame(controls, withheld, tick);
    case "subsurface_resonance_station":
      return subsurfaceFrame(controls, withheld, tick);
    case "quantum_state_institute":
      return quantumFrame(controls, withheld, tick);
  }
}
