# Automatic game-state summary charts

Every successful `/interior act summarize` response contains a compact authoritative action receipt
and one freshly generated PNG chart. The receipt states what was recorded, its cost, the cycle
effect, what to do next, and what remains outstanding. `/interior recall` remains the complete
searchable public ledger.

## Pipeline and state consistency

The database mutation already returns the exact committed `state_after`. The deterministic engine
now retains that state on its request-local outcome. `GameService` immediately serializes it,
together with the current immutable puzzle definition and public resource lines, into a frozen
`SummarySnapshot`.

That one snapshot supplies:

1. the compact summary receipt and its cycle/navigation fields;
2. the current phase footer;
3. normalized participation, conditions, public systems, reactions, counters, and requirements;
4. the attachment position and cycle.

No post-action game-state query is used for a successful summary. Concurrent requests therefore
cannot replace one another's chart or silently mix text from one state version with an image from
another. SVG strings, PNG buffers, filenames, and Discord `File` objects are all request-local.
There is no image cache or shared current-output filename; even identical state is rendered again.

## SVG and PNG rendering

[`src/uniflora/summary_chart.py`](../src/uniflora/summary_chart.py) contains the immutable snapshot
and chart models, public-state normalization, conservative text wrapping, section measurement,
standalone SVG generation, filename sanitization, and PNG conversion.

The renderer generates a 1200-unit-wide standalone SVG with an opaque background, internal CSS,
an accessible `title` and `desc`, system-font stacks, and no external resources. It begins at
1200 × 675 and expands vertically when its measured sections need more room. Long inherited or
condition prose receives an explicit ellipsis and a reminder that complete details remain in the
text. Public thresholds, actions, and counters are not silently cropped.

PNG conversion uses `resvg_py` and its in-memory `svg_to_bytes` API at 2× width. It uses prebuilt
Rust-backed wheels and needs no Cairo, browser, screenshot tool, temporary file, or network request
at render time. The Docker image installs DejaVu and Liberation system fonts for consistent text;
these font packages are the only related native packages.

Visual constants such as dimensions, scale, and the restrained status palette are at the top of
`summary_chart.py`. Color is paired with status text, structural markers, and threshold lines.
Counter direction remains neutral unless game data explicitly defines a direction.

## Discord delivery and failure behavior

The summarize interaction is deferred once after authorization. Rendering runs in a worker thread
so the bot event loop remains responsive. The first follow-up contains the first textual chunk and
the PNG attachment; any later 2,000-character text chunks are sent without duplicate attachments.
The existing public/test visibility and test-surface marker are preserved.

Rendering errors are logged with their traceback for maintainers. The accepted game action is not
rolled back or repeated. Because the chart is unavailable, Discord falls back to the complete
ordinary textual summary plus:

> The visual state chart could not be generated for this summary.

No local path, traceback, credential, or renderer detail is exposed to players.

## Development fixture

Render the Position 1 sample without Discord:

```powershell
.venv\Scripts\python.exe -m uniflora.summary_fixture
```

Use `--output-dir PATH` to choose another destination. The default `render-output/` directory is
ignored by Git and Docker. It receives both the standalone SVG and its PNG conversion, making it
possible to inspect layout and XML independently.

## Files created or modified

- `src/uniflora/summary_chart.py`: snapshot, normalization, SVG layout, and PNG rendering.
- `src/uniflora/summary_fixture.py`: developer fixture entry point.
- `src/uniflora/engine/core.py`: retains the committed mutation snapshot.
- `src/uniflora/game_service.py`: builds and renders summary charts with fallback behavior.
- `src/uniflora/discord_adapter.py`: defers summaries and sends one in-memory attachment.
- `tests/test_summary_chart.py` and `tests/test_discord_adapter.py`: rendering and transport tests.
- `pyproject.toml`, `Dockerfile`, `.gitignore`, and `.dockerignore`: dependency, fonts, and ignored
  fixture output.

## Current layout limits

Text width is estimated conservatively rather than measured through a platform-specific font API,
so exact line breaks can differ slightly between Windows development and the Linux container.
The included font fallbacks and generous line heights keep those differences from overlapping
sections. Exceptionally dense public states may produce a chart taller than the preferred 1800
SVG units rather than dropping a threshold, available action, or persistent counter.
