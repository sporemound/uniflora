import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { transformWithOxc } from "vite";

const activityRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(activityRoot, "..");
const packPath = resolve(
  repositoryRoot,
  "src/uniflora/content/v2/packs/missing_interior/pack.yaml",
);
const accessSourcePath = resolve(
  activityRoot,
  "src/shared/investigation-access.ts",
);
const routesSourcePath = resolve(activityRoot, "src/lib/routes.ts");
const accessViewSourcePath = resolve(
  activityRoot,
  "src/components/AccessView.tsx",
);
const primaryNavigationSourcePath = resolve(
  activityRoot,
  "src/components/PrimaryNavigation.tsx",
);
const cartographyViewSourcePath = resolve(
  activityRoot,
  "src/components/CartographyView.tsx",
);
const publicStatePath = resolve(activityRoot, "src/shared/public-state.ts");

const expectedFacilities = [
  { id: "boundary_array", name: "Boundary Array" },
  {
    id: "aeronautical_incident_center",
    name: "Aeronautical Incident Center",
  },
  { id: "aerial_phenomena_archive", name: "Aerial Phenomena Archive" },
  { id: "holography_laboratory", name: "Holography Laboratory" },
  {
    id: "subsurface_resonance_station",
    name: "Subsurface Resonance Station",
  },
  { id: "quantum_state_institute", name: "Quantum State Institute" },
];

const expectedPositions = [
  {
    id: "network_orientation",
    ordinal: 0,
    title: "The Network Before the Event",
    focusLocationId: "boundary_array",
    nextPositionId: "boundary_event",
  },
  {
    id: "boundary_event",
    ordinal: 1,
    title: "First Return",
    focusLocationId: "boundary_array",
    nextPositionId: "aeronautical_incident",
  },
  {
    id: "aeronautical_incident",
    ordinal: 2,
    title: "The Track That Will Not Close",
    focusLocationId: "aeronautical_incident_center",
    nextPositionId: "archive_convergence",
  },
  {
    id: "archive_convergence",
    ordinal: 3,
    title: "A Pattern Without a Common Cause",
    focusLocationId: "aerial_phenomena_archive",
    nextPositionId: "holographic_reconstruction",
  },
  {
    id: "holographic_reconstruction",
    ordinal: 4,
    title: "The Volume Defined by Its Absence",
    focusLocationId: "holography_laboratory",
    nextPositionId: "subsurface_resonance",
  },
  {
    id: "subsurface_resonance",
    ordinal: 5,
    title: "A Mode Without a Source Point",
    focusLocationId: "subsurface_resonance_station",
    nextPositionId: "quantum_state",
  },
  {
    id: "quantum_state",
    ordinal: 6,
    title: "The View From the Missing Interior",
    focusLocationId: "quantum_state_institute",
    nextPositionId: null,
  },
];

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function yamlScalar(value) {
  const trimmed = value.trim();
  if (trimmed === "null" || trimmed === "~") return null;
  if (/^\d+$/.test(trimmed)) return Number.parseInt(trimmed, 10);
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function topLevelSection(source, name, nextName) {
  const startMarker = `${name}:\n`;
  const start = source.indexOf(startMarker);
  assert.notEqual(start, -1, `pack is missing the ${name} section`);

  const contentStart = start + startMarker.length;
  const endMarker = `\n${nextName}:`;
  const end = source.indexOf(endMarker, contentStart);
  assert.notEqual(end, -1, `pack is missing the ${nextName} section`);
  return source.slice(contentStart, end);
}

function parseTopLevelSequence(section, keys) {
  const records = [];
  let current = null;

  for (const line of section.split("\n")) {
    const idMatch = /^- id:\s*(.+?)\s*$/.exec(line);
    if (idMatch) {
      current = { id: yamlScalar(idMatch[1]) };
      records.push(current);
      continue;
    }

    if (!current) continue;
    const fieldMatch = /^  ([a-z_]+):\s*(.*?)\s*$/.exec(line);
    if (fieldMatch && keys.has(fieldMatch[1])) {
      current[fieldMatch[1]] = yamlScalar(fieldMatch[2]);
    }
  }

  return records;
}

function assertExport(source, kind, name, sourcePath) {
  assert.match(
    source,
    new RegExp(`\\bexport\\s+${kind}\\s+${escapeRegExp(name)}\\b`),
    `${sourcePath} must export ${name}`,
  );
}

function assertNearbyLiterals(source, anchor, values, label) {
  const quotedAnchor = new RegExp(`["'\`]${escapeRegExp(anchor)}["'\`]`, "g");
  const indexes = [];
  let match;

  while ((match = quotedAnchor.exec(source)) !== null) {
    indexes.push(match.index);
  }

  assert.ok(indexes.length > 0, `${label} is missing ${anchor}`);
  const found = indexes.some((index) => {
    const window = source.slice(Math.max(0, index - 120), index + 900);
    return values.every((value) => {
      if (value === null) {
        return /next(?:PositionId|_position_id)\s*:\s*null/.test(window);
      }
      if (typeof value === "number") {
        return new RegExp(`\\bordinal\\s*:\\s*${value}\\b`).test(window);
      }
      return new RegExp(`["'\`]${escapeRegExp(String(value))}["'\`]`).test(
        window,
      );
    });
  });

  assert.ok(found, `${label} does not preserve the canonical mapping for ${anchor}`);
}

const packSource = (await readFile(packPath, "utf8")).replace(/\r\n/g, "\n");
const accessSource = await readFile(accessSourcePath, "utf8");
const routesSource = await readFile(routesSourcePath, "utf8");
const accessViewSource = await readFile(accessViewSourcePath, "utf8");
const primaryNavigationSource = await readFile(
  primaryNavigationSourcePath,
  "utf8",
);
const cartographyViewSource = await readFile(cartographyViewSourcePath, "utf8");
const publicStateSource = await readFile(publicStatePath, "utf8");
const publicStateJavaScript = (
  await transformWithOxc(publicStateSource, publicStatePath)
).code;
const {
  MOCK_PUBLIC_STATE,
  normalizePublicActivitySnapshot,
} = await import(
  `data:text/javascript;base64,${Buffer.from(publicStateJavaScript).toString("base64")}`
);
const routesJavaScript = (await transformWithOxc(routesSource, routesSourcePath))
  .code;
const {
  activityHref,
  parseActivityRoute,
} = await import(
  `data:text/javascript;base64,${Buffer.from(routesJavaScript).toString("base64")}`
);

assert.match(packSource, /^schema_version:\s*3\s*$/m);
assert.match(packSource, /^  id:\s*missing_interior\s*$/m);
assert.match(packSource, /^  content_version:\s*2\.0\.0-strategic-overhaul\s*$/m);
assert.match(packSource, /^  initial_position_id:\s*network_orientation\s*$/m);

const packFacilities = parseTopLevelSequence(
  topLevelSection(packSource, "locations", "positions"),
  new Set(["name"]),
);
const packPositions = parseTopLevelSequence(
  topLevelSection(packSource, "positions", "roles"),
  new Set([
    "ordinal",
    "title",
    "focus_location_id",
    "next_position_id",
  ]),
).map((position) => ({
  id: position.id,
  ordinal: position.ordinal,
  title: position.title,
  focusLocationId: position.focus_location_id,
  nextPositionId: position.next_position_id || null,
}));

assert.deepEqual(
  packFacilities,
  expectedFacilities,
  "canonical facility IDs, names, or order changed",
);
assert.deepEqual(
  packPositions,
  expectedPositions,
  "canonical position IDs, order, titles, focus, or next mapping changed",
);
assert.deepEqual(
  packPositions.map(({ ordinal }) => ordinal),
  [0, 1, 2, 3, 4, 5, 6],
  "position ordinals must be contiguous",
);
assert.equal(
  new Set(packPositions.slice(1).map(({ focusLocationId }) => focusLocationId)).size,
  expectedFacilities.length,
  "each canonical position must focus a distinct canonical facility",
);

for (const [index, position] of packPositions.entries()) {
  assert.equal(
    position.focusLocationId,
    packFacilities[Math.max(0, index - 1)].id,
    `${position.id} must focus the facility assigned to its progression ordinal`,
  );
  assert.equal(
    position.nextPositionId,
    packPositions[index + 1]?.id ?? null,
    `${position.id} must point to the next canonical position`,
  );
}

assertExport(
  accessSource,
  "const",
  "CANONICAL_POSITIONS",
  "src/shared/investigation-access.ts",
);
assertExport(
  accessSource,
  "const",
  "CANONICAL_FACILITIES",
  "src/shared/investigation-access.ts",
);
assertExport(
  accessSource,
  "(?:function|const)",
  "buildAccessDisplayModel",
  "src/shared/investigation-access.ts",
);

for (const facility of expectedFacilities) {
  assertNearbyLiterals(
    accessSource,
    facility.id,
    [facility.name],
    "CANONICAL_FACILITIES",
  );
}
for (const position of expectedPositions) {
  assertNearbyLiterals(
    accessSource,
    position.id,
    [
      position.ordinal,
      position.title,
      position.focusLocationId,
      position.nextPositionId,
    ],
    "CANONICAL_POSITIONS",
  );
}

for (const literal of [
  "completed",
  "available",
  "locked",
  "unpublished",
  "read-only",
  "none",
  "unknown",
]) {
  assert.match(
    accessSource,
    new RegExp(`["'\`]${escapeRegExp(literal)}["'\`]`),
    `access display model must represent ${literal}`,
  );
}
assert.match(
  accessSource,
  /\bisCurrent\b/,
  "position currentness must remain separate from progression",
);
assert.match(
  accessSource,
  /\bisFocus\b/,
  "facility focus must remain separate from availability",
);
assert.match(
  accessSource,
  /\baccessMode\b/,
  "facility access mode must be explicit",
);

assertExport(
  routesSource,
  "(?:function|const)",
  "parseActivityRoute",
  "src/lib/routes.ts",
);
assertExport(
  routesSource,
  "(?:function|const)",
  "activityHref",
  "src/lib/routes.ts",
);
assert.match(routesSource, /["'`]\/facilities["'`]/);
assert.match(routesSource, /["'`]\/positions["'`]/);
assert.match(routesSource, /["'`]\/cartography["'`]/);
assert.match(primaryNavigationSource, /\/facilities/);
assert.match(primaryNavigationSource, /\/positions/);
assert.match(primaryNavigationSource, /\/cartography/);
assert.match(cartographyViewSource, /GeographicFieldMap/);
assert.match(cartographyViewSource, /anomalyLayers=\{anomalyLayers\}/);
assert.match(accessViewSource, /Read-only console/i);
assert.match(
  accessViewSource,
  /Opening a console does not move your player or change investigation state\./i,
);
assert.match(accessViewSource, /\blocked\b/i);
assert.match(accessViewSource, /\baccessMode\b/);

const combinedActivitySource = [
  accessSource,
  routesSource,
  accessViewSource,
  primaryNavigationSource,
  cartographyViewSource,
].join("\n");
assert.doesNotMatch(
  combinedActivitySource,
  /\b(fetch|XMLHttpRequest)\s*\([^)]*\/(?:move|position\/complete|complete-position)/i,
  "catalogue navigation must not invoke movement or position-completion APIs",
);

const facilityDeepLink = parseActivityRoute(
  "https://activity.invalid/facilities/boundary-array?environment=test&room=lab",
);
assert.deepEqual(
  facilityDeepLink,
  {
    kind: "facility",
    pathname: "/facilities/boundary-array",
    search: "?environment=test&room=lab",
    slug: "boundary-array",
  },
  "facility deep links must parse without losing query context",
);
assert.equal(
  activityHref("/positions", facilityDeepLink),
  "/positions?environment=test&room=lab",
  "catalogue links must preserve environment and room context",
);
const cartographyDeepLink = parseActivityRoute(
  "https://activity.invalid/cartography?environment=test&room=lab&instance=activity-7",
);
assert.deepEqual(
  cartographyDeepLink,
  {
    kind: "cartography",
    pathname: "/cartography",
    search: "?environment=test&room=lab&instance=activity-7",
  },
  "cartography deep links must parse without losing Activity context",
);
assert.equal(
  activityHref("/cartography", facilityDeepLink),
  "/cartography?environment=test&room=lab",
  "cartography links must preserve the current Activity query",
);
assert.equal(
  parseActivityRoute("/facilities/not/a-slug").kind,
  "not-found",
  "nested or malformed facility paths must fail to an explicit 404 route",
);

const signedLegacySnapshot = {
  ...structuredClone(MOCK_PUBLIC_STATE),
  source: "hypha",
  revision: 1,
  stateHeadHash: "validated-access-r1",
};
const normalizedLegacy = normalizePublicActivitySnapshot(signedLegacySnapshot);
assert.ok(normalizedLegacy, "the signed legacy fixture must normalize");
assert.notEqual(
  normalizedLegacy,
  signedLegacySnapshot,
  "public snapshots must be reconstructed rather than returned by reference",
);
assert.equal(
  normalizePublicActivitySnapshot({
    ...signedLegacySnapshot,
    players: [{ participantId: "must-not-publish" }],
  }),
  null,
  "unknown private root fields must fail closed",
);
const nestedLeak = structuredClone(signedLegacySnapshot);
nestedLeak.locations[0].token = "must-not-publish";
assert.equal(
  normalizePublicActivitySnapshot(nestedLeak),
  null,
  "unknown private nested fields must fail closed",
);

const canonicalLocations = expectedFacilities.map((facility, index) => ({
  id: facility.id,
  name: facility.name,
  shortName: facility.name,
  status: index === 0 ? "focus" : "locked",
  timezone: "UTC",
  activeAssignments: 0,
}));
const signedCanonicalSnapshot = {
  ...signedLegacySnapshot,
  schemaVersion: "2.1.0",
  positionId: expectedPositions[0].id,
  positionTitle: expectedPositions[0].title,
  focusLocationId: expectedFacilities[0].id,
  locations: canonicalLocations,
  assignments: [],
  positions: expectedPositions.map((position, index) => ({
    id: position.id,
    ordinal: position.ordinal,
    title: position.title,
    locationId: position.focusLocationId,
    progression: index === 0 ? "available" : "locked",
    consoleMode: index === 0 ? "workspace" : "locked",
  })),
};
assert.ok(
  normalizePublicActivitySnapshot(signedCanonicalSnapshot),
  "the canonical 2.1 access projection must normalize",
);
assert.equal(
  normalizePublicActivitySnapshot({
    ...signedCanonicalSnapshot,
    positions: signedCanonicalSnapshot.positions.map((position, index) =>
      index === 1
        ? { ...position, consoleMode: "workspace" }
        : position,
    ),
  }),
  null,
  "a locked position cannot publish an enterable console mode",
);
assert.equal(
  normalizePublicActivitySnapshot({
    ...signedCanonicalSnapshot,
    positions: [
      signedCanonicalSnapshot.positions[0],
      signedCanonicalSnapshot.positions[0],
      ...signedCanonicalSnapshot.positions.slice(2),
    ],
  }),
  null,
  "duplicate public position identifiers and ordinals must fail closed",
);
assert.equal(
  normalizePublicActivitySnapshot({
    ...signedCanonicalSnapshot,
    positions: signedCanonicalSnapshot.positions.map((position, index) =>
      index === 0
        ? {
            ...position,
            locationId: expectedFacilities[1].id,
          }
        : index === 1
          ? {
              ...position,
              locationId: expectedFacilities[0].id,
            }
          : position,
    ),
  }),
  null,
  "canonical progression cannot be remapped to a different facility",
);
assert.equal(
  normalizePublicActivitySnapshot({
    ...signedCanonicalSnapshot,
    positionTitle: "A valid-looking but noncanonical title",
    positions: signedCanonicalSnapshot.positions.map((position, index) =>
      index === 0
        ? { ...position, title: "A valid-looking but noncanonical title" }
        : position,
    ),
  }),
  null,
  "canonical position titles must match the versioned pack contract",
);
assert.equal(
  normalizePublicActivitySnapshot({
    ...signedCanonicalSnapshot,
    positions: signedCanonicalSnapshot.positions.slice(0, -1),
  }),
  null,
  "partial canonical position projections must fail closed",
);

console.log(
  JSON.stringify(
    {
      ok: true,
      validator: "position-access",
      pack: {
        id: "missing_interior",
        schemaVersion: 3,
        contentVersion: "2.0.0-strategic-overhaul",
      },
      facilities: packFacilities.map(({ id }) => id),
      positions: packPositions.map(
        ({ id, ordinal, focusLocationId, nextPositionId }) => ({
          id,
          ordinal,
          focusLocationId,
          nextPositionId,
        }),
      ),
      routes: [
        "/facilities",
        "/facilities/:slug",
        "/positions",
        "/positions/:slug",
        "/cartography",
      ],
      mutationFreeNavigation: true,
      publicProjection: {
        schemas: ["2.0.0", "2.1.0", "2.2.0", "2.3.0", "2.4.0"],
        closedAllowlist: true,
        canonicalAssociation: true,
        normalizedBeforePersistence: true,
      },
    },
    null,
    2,
  ),
);
