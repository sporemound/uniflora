export interface PublicMapSample {
  sampleId: string;
  latitude: number;
  longitude: number;
  observedAt: string;
  uncertaintyKm: number;
  sourceReference: string;
}

export interface PublicTrajectoryLayer {
  layerId: string;
  kind: "trajectory";
  label: string;
  samples: PublicMapSample[];
}

export interface PublicHeatmapCell {
  cellId: string;
  latitude: number;
  longitude: number;
  intensity: number;
  radiusKm: number;
  sourceReferences: string[];
}

export interface PublicHeatmapLayer {
  layerId: string;
  kind: "heatmap";
  label: string;
  cells: PublicHeatmapCell[];
}

export type PublicAnomalyMapLayer = PublicTrajectoryLayer | PublicHeatmapLayer;
