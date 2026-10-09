# Position state and facility access

The Activity exposes one read-only public catalogue for the six canonical
positions and facilities in **The Missing Interior** content pack. Catalogue
navigation changes only the browser route. It does not move a player, complete
a position, unlock a facility, or write investigation state.

## Routes

The route families use kebab-case versions of canonical underscore IDs:

| Route | Purpose |
| --- | --- |
| `/facilities` | All six facilities and their published availability |
| `/facilities/boundary-array` | Boundary Array access shell |
| `/facilities/aeronautical-incident-center` | Aeronautical Incident Center access shell |
| `/facilities/aerial-phenomena-archive` | Aerial Phenomena Archive access shell |
| `/facilities/holography-laboratory` | Holography Laboratory access shell |
| `/facilities/subsurface-resonance-station` | Subsurface Resonance Station access shell |
| `/facilities/quantum-state-institute` | Quantum State Institute access shell |
| `/positions` | All six canonical positions and their published progression |
| `/positions/<position-slug>` | One position status shell; for example, `/positions/boundary-event` |

The route helpers preserve the active `environment` and room query parameters
when moving between catalogue pages. A route is an address for a public view,
not an authorization mechanism.

## Two state projections

The public-state reader accepts a transitional 2.0 projection and the
authoritative 2.1 shape, but it does not pretend that both carry the same
information.

### Transitional 2.0

The 2.0 snapshot has one flat `positionId`, `positionTitle`, and
`focusLocationId`, plus a list of facility-like locations. Existing 2.0 Hypha
publications use legacy/synthetic IDs, so they cannot authoritatively describe
the six canonical v2 positions.

For a signed Hypha 2.0 snapshot:

- canonical positions are shown with `progression: "unpublished"` and
  `isCurrent: false`;
- a canonical facility may inherit only its explicitly published location
  availability through the documented legacy-ID adapter;
- an explicitly available or focused facility gets `accessMode: "read-only"`;
- an explicitly locked facility gets `accessMode: "none"`;
- no position completion or current-position claim is inferred from list order.

A mock snapshot, a failed fetch, or an unrecognized location produces
`availability: "unknown"` and `accessMode: "unknown"`. It never grants access.

### Authoritative 2.1

The 2.1 projection publishes all six canonical `positions` and their facility
associations. A position may state progression as `completed`, `available`, or
`locked`; `unpublished` is a browser fallback used only when canonical
progression was not published. The normalizer rejects partial collections,
altered titles, reordered ordinals, duplicate IDs, and position-to-facility
remapping before anything is persisted or rendered. Currentness remains a
separate `isCurrent` flag because the final current position may also be
complete.

Facility state also uses separate axes:

- `availability`: `available`, `locked`, or `unknown`;
- `isFocus`: whether the publication identifies the facility as the current
  focus;
- `accessMode`: `read-only`, `none`, or `unknown`.

The 2.1 publisher is the authority for those values. The browser catalogue only
normalizes and renders the signed projection; it does not calculate unlocks
from the canonical sequence.

## Read-only consoles and locked shells

An available facility route presents its public console shell in read-only
mode. Opening that shell does not call the v2 movement command and does not
change `player_current_location_id`. Movement remains an authenticated engine
operation with its own availability checks.

A locked facility remains visible in the catalogue so the world is legible,
but its direct route renders a locked shell. It does not reveal facility
evidence, instruments, role work, or completion controls. Typing or sharing the
URL cannot bypass the published lock. Unknown state fails closed in the same
way and explains that authoritative access has not been published.

Position routes follow the same rule: their status and canonical public
metadata may be visible, but a route cannot complete, advance, or unlock a
position.

## Position 1 and solo testing

The available Boundary Array shell includes a read-only Position 1 checklist.
One player may rotate through the Field Observer, Instrument Operator,
Atmospheric Analyst, Signal Correlator, and Protocol Auditor roles to inspect
the optical, radio, diagnostic, and weather records and complete the six
required actions.

Completion still requires an assessment that cites at least three source
classes, the tested atmospheric-propagation explanation, the preserved
optical/radio timing contradiction, and the documented upper-atmosphere gap.
The engine then requires one confirmation from a player other than the
assessment author. A sole human tester may use two clearly separate test
identities, but one identity cannot self-confirm and the public Activity does
not execute or bypass that authoritative rule.

## Scientific view scope

Facility pages render a scientific-domain schematic so the network remains
legible, but a schematic is explicitly not measured data. A data-backed
facility view may mount only when a signed publication identifies both that
canonical facility and its position.

The current SR-03 Phase 3 publication is a transitional
`interfacility-intake` / `position-0` fixture. It remains available in the
shared Workspace and retains that provenance; the Boundary Array route does not
rename or present it as Boundary evidence. The production Boundary
clock-alignment method can populate that console after a matching facility
projection is published. The other five facilities require their own bounded
datasets and deterministic methods before data visualizations can replace their
schematics.

The Python HoloViews/Panel/Bokeh stack remains the local analysis and
publication producer. The public Activity consumes only signed, reduced JSON
and deterministic image assets, then renders those with browser-native
SVG/canvas. This keeps the browser bundle small and prevents a facility route
from gaining access to the local research store.

## Privacy and authority boundary

The catalogue combines two allowlisted sources:

1. public names, IDs, order, titles, and focus/next relationships from
   `src/uniflora/content/v2/packs/missing_interior/pack.yaml`; and
2. the validated public Activity snapshot.

It must not expose player IDs, Discord identity, room tickets, session data,
state commands, private role assignments, unreleased evidence, completion
requirements not deliberately allowlisted from the public pack, or raw
persistence records. Those remain on the authenticated/authoritative side of
the system. Adding a route does not expand the publication allowlist.

## Validation

From `activity/`, run:

```powershell
npm run validate:position-access
```

The validator checks the exact six-facility and six-position catalogue against
the canonical pack, including order, titles, focus facilities, and next-position
links. It also checks the Activity catalogue exports, route helpers, state axes,
and the absence of direct movement/completion calls in catalogue navigation.
