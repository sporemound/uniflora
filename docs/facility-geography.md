# Facility geography

The Missing Interior uses six WGS84 facility sites. The coordinates
anchor maps, time zones, bearings, uncertainty regions, trajectories, and
heatmaps.

Public maps state a 25 km coordinate precision. Scientific observations may
carry smaller uncertainty regions when their source record supports
that precision, but facility artwork and prose should use the sector label
rather than a street address.

| Position | Facility | Sector | Latitude | Longitude | Time zone |
|---:|---|---|---:|---:|---|
| 1 | Boundary Array | Black Rock Sector, Nevada | 40.88 | -119.05 | America/Los_Angeles |
| 2 | Aeronautical Incident Center | Allegheny Sector, West Virginia | 38.73 | -80.21 | America/New_York |
| 3 | Aerial Phenomena Archive | Driftless Sector, Wisconsin | 43.25 | -90.88 | America/Chicago |
| 4 | Holography Laboratory | San Luis Sector, Colorado | 37.73 | -105.91 | America/Denver |
| 5 | Subsurface Resonance Station | Cascadia Sector, Washington | 47.45 | -123.53 | America/Los_Angeles |
| 6 | Quantum State Institute | Adirondack Sector, New York | 44.12 | -74.31 | America/New_York |

The authoritative definitions live in
`src/uniflora/content/v2/packs/missing_interior/pack.yaml`. The v2 Activity
projection publishes a closed `mapCoordinates` object containing latitude,
longitude, sector label, public precision, and coordinate basis.

## Anomaly layer contract

The Activity accepts two provenance-bearing public layer shapes defined in
`activity/src/shared/geospatial.ts`:

- `trajectory`: ordered observations with timestamps, uncertainty radii, and
  source references;
- `heatmap`: intensity cells with radii and source-reference collections.

No anomaly path or heat field is inferred from facility order. A layer appears
only after observations are published. Missing samples remain gaps; uncertainty
is rendered rather than silently smoothed away. Facility coverage halos are
interface context and are not anomaly evidence.

Live reference layers are registered separately in
`activity/src/shared/external-map-layers.ts`. The registry is closed to NASA
GIBS, NOAA/NWS, and the bounded public-report snapshot; it does not accept
participant-supplied endpoints. Reference visibility and timeline position are
display state only.

## Mapping rules

1. Use WGS84 longitude/latitude at all ingestion and publication boundaries.
2. Preserve the original observation time and source reference on every
   trajectory sample.
3. Store uncertainty with each sample or heat cell.
4. Do not connect observations across an unrecorded interval unless the layer
   explicitly identifies the segment as an interpolation.
5. Do not expose private participant locations, live device coordinates,
   callsigns, or external-feed exact coordinates.
6. Geographic layers are advisory scientific output and never advance
   authoritative game state.
