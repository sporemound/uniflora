# Uniflora: The Missing Interior

Uniflora is a cooperative investigation game with a deterministic Python game engine and a React/Cloudflare web client. Players examine evidence, choose roles, and work through a seven-position campaign. The older Discord interface remains in the source for compatibility.

This repository is a public source snapshot with fresh Git history. It contains no live game database, player records, account-specific deployment IDs, or populated credentials. The bundled scientific case in `activity/public/science/artifact-phase3-sr03/` is synthetic test data. Public snapshots and external UFO-report datasets from the original deployment are omitted.

## Run locally

Requirements: Python 3.11+ and Node.js 22+.

```sh
python -m venv .venv
python -m pip install -e '.[dev]'
python -m pytest
```

The Python web service is started with `missing-interior-web`. Copy `web-game.env.example` into your own environment configuration and supply independent secrets and a local database path.

For the web client:

```sh
cd activity
npm ci
npm run build
npm run dev
```

Copy `activity/.dev.vars.example` to `activity/.dev.vars` for local Worker development. The web client needs its own D1 databases, a signing secret shared with the Python service, and a configured email provider before sign-in and multiplayer features work. Set those values locally or in your host's secret store. Do not commit populated environment files. The Cloudflare configuration files contain dummy database IDs and an example origin; replace them when deploying your own instance.

## Code and content

- `src/uniflora/`: game engine, content, service, and legacy Discord adapter.
- `activity/`: React client, Cloudflare Worker, migrations, and validation tools.
- `research_dashboard/`: analysis and publishing tools.
- `external_feeds/`: optional external source adapters.
- `tests/`: Python tests.
- `docs/`: architecture, rules, authoring, and testing guides.

The game does not need an OpenAI or Gemini key for deterministic play. Optional model features require their own credentials and privacy settings. See the `.env.example` files for available settings.

## Privacy and security

Participant records belong in a private database. Never commit event streams, chat logs, emails, API keys, tokens, private keys, populated `.env` files, or generated public-state snapshots. The `.gitignore` excludes common local files, but review every commit before publication. A fresh Git history was used here so private commits and author metadata from the source repository are not copied.

## License

GPL-3.0-only. See [LICENSE](LICENSE). Third-party packages are installed separately and retain their own licenses.
