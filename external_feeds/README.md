# aprs.fi Exterior Register for The Missing Interior

This package replaces the direct APRS-IS listener with an **on-demand,
named-target aprs.fi client**.

It is centered conceptually on:

```text
25°43′42″N 32°36′05″E
25.728333, 32.601389
```

The center is used only to convert returned station positions into a coarse
bearing and distance band. Exact coordinates and callsigns are not shown in
Discord.

## Why this version is on-demand

The aprs.fi API documentation says:

- requests must be made when data is actively needed by an end user
- caching is encouraged
- up to 20 named targets can be batched
- wildcard/geographic discovery is intentionally unsupported
- the application must identify its name, version and project URL in
  `User-Agent`
- aprs.fi must be credited as the source

Accordingly, this package is intended for a command such as:

```text
/interior exterior
```

It does not run a random background polling loop.

## What it queries

Implemented:

- `what=loc`
- `what=wx`

Not implemented:

- `what=msg`

APRS text-message retrieval is intentionally omitted to avoid copying personal
radio traffic into Discord.

## Install

From the `external_feeds` folder, run:

```powershell
.\install_into_project.ps1 -ProjectRoot ..
```

The destination is relative to the project root you provide:

```text
src\uniflora\external_feeds\aprsfi
```

## Configure targets

Edit:

```text
src\uniflora\external_feeds\aprsfi\targets.json
```

Example:

```json
{
  "targets": [
    {
      "name": "CALLSIGN-1",
      "location": true,
      "weather": false,
      "enabled": true
    },
    {
      "name": "WEATHER-ID",
      "location": false,
      "weather": true,
      "enabled": true
    }
  ]
}
```

The API cannot discover stations by radius. Use the aprs.fi map manually to
identify fixed stations or weather stations that you actually want to query.

Maximum enabled targets: 20.

## Environment variables

```powershell
$env:UNIFLORA_APRSFI_API_KEY = "your-api-key"
$env:UNIFLORA_APRSFI_ALIAS_SECRET = python -c "import secrets; print(secrets.token_hex(32))"
$env:UNIFLORA_APRSFI_PROJECT_URL = "https://your-public-project-page.example"
$env:UNIFLORA_APRSFI_CACHE_SECONDS = "1800"
$env:UNIFLORA_APRSFI_MAX_ENTRIES = "4"
```

The project URL is required because aprs.fi requires it in the HTTP
`User-Agent`.

Do not commit the API key or alias secret.

## Preview from PowerShell

After installation, with the project environment active:

```powershell
python -m uniflora.external_feeds.aprsfi.preview `
  --targets ".\src\uniflora\external_feeds\aprsfi\targets.json"
```

## Discord integration

Review:

```text
hypha_integration_example.py
```

It shows:

- service construction in `InteriorBot.__init__`
- an `/interior exterior` command
- optional use of Hypha's voice attachment builder
- cleanup in `InteriorBot.close()`

The bridge sends one Discord message containing the BBS report and optional
voice attachment.

## Privacy reductions

The public report excludes:

- exact station identifiers
- exact coordinates
- raw comments
- status text
- packet paths
- source/destination callsigns
- AIS identifiers
- APRS message contents

Each configured target receives a salted daily alias such as:

```text
exterior station 014
```

Locations become:

```text
bearing: southwest
range: 100–200 km
```

## Cache

The first command request fetches current data. Requests during the next
30 minutes use the shared in-memory cache by default. This reduces API load and
matches the documented recommendation to cache results.

## Tests

From the extracted package:

```powershell
$env:PYTHONPATH = ".\src"
python -m unittest discover -s tests -v
```
