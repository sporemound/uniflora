# Uniflora web client

This folder contains the React site and Cloudflare Worker. The Worker manages web sessions and collaboration rooms; the Python service owns the authoritative game state.

## Local development

Install Node.js 22+, run `npm ci`, then `npm run dev`. Copy `.dev.vars.example` to `.dev.vars` and fill only the values needed for the feature you are testing. Keep `.dev.vars` private. `npm run build` checks TypeScript and builds the site.

For a Cloudflare deployment, create your own D1 databases, replace the dummy IDs in `wrangler.jsonc` or `wrangler.preview.jsonc`, and set your own Worker secrets. The preview configuration's `APP_ORIGIN` is an example domain; replace it with your site origin. Apply the migrations from `migrations/`, `chat-migrations/`, or `preview-migrations/` to the matching database before using those features.

The Worker expects a separately configured Python game service for authoritative status and commands. The optional email sign-in and AI chat features need credentials supplied through the host's secret store. No deployed endpoints, user database, or live state snapshots are included in this repository.
