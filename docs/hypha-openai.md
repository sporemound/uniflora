# Hypha with OpenAI

Hypha can use an OpenAI project API key for dialogue while retaining its persona,
authorized case context, conversation history, game authority boundaries, local
eSpeak voice, and existing presentation modes. Gemini remains selectable.
Provider failures do not silently fall back to another vendor or billing path.

## API access and included Pro credits

An API key is separate from signing in to ChatGPT. Eligible paid Pro subscriptions
can claim included API credits in ChatGPT **Settings → Billing → API credits**, or
in API Platform billing, using the same email and an API organization they own.
Eligibility and the issued balance must be verified before activation. Do not
assume a ChatGPT subscription alone has already funded the API organization.

- [API credits for ChatGPT subscribers](https://developers.openai.com/api/docs/guides/chatgpt-api-credits)
- [OpenAI API quickstart](https://developers.openai.com/api/docs/quickstart)

The documented credit benefit currently requires an eligible paid subscription
at least seven days old. Credits expire at the end of the billing cycle. No API
payment method is required to use active free credits; purchased credits may be
used after a free balance runs out. Leave paid auto-recharge off unless wanted.

## Public Cloudflare Hypha chat

Set these runtime values on the existing Worker, without putting secrets in the
repository or browser bundle:

| Setting | Value |
| --- | --- |
| `HYPHA_CHAT_PROVIDER` | `openai` |
| `OPENAI_API_KEY` | Secret project API key for the credited API organization |
| `OPENAI_PRIVACY_ACKNOWLEDGED` | `true` |
| `OPENAI_CHAT_MODEL` | `gpt-6-luna`, after verifying model access |
| `OPENAI_CHAT_REASONING_EFFORT` | `none` |

Requests use the Responses API, `store: false`, bounded output and a 20-second
timeout. Only completed assistant text is accepted. No automatic retry or
cross-provider fallback occurs. Existing auth, public history, quotas, and guest
limits still apply. Health readiness reports configuration, not successful
inference or available credits. Verify one controlled request before reporting
Hypha restored.

Accepted signed-in messages are stored before reply generation. If the provider
rejects a request, times out, or returns unusable output, the participant's message
remains in the shared transcript with a failed Hypha connection notice. Safe
failure categories distinguish credit, credential, model and temporary service
problems without exposing API keys, upstream response bodies, or participant
input. Failed generation never creates action proposals or audio.

The existing live `missing-interior-web-preview` deployment contains modules from
multiple projects. Neither repository alone reproduces it. Use
`tools/patch_live_openai.mjs` against a freshly downloaded live module directory
for a narrow patch. It preserves current prompts and action-confirmation logic,
modifies only the selected chat transport and its readiness checks, and refuses
an unexpected baseline. Retain every other module, existing asset storage,
bindings, Durable Object exports, domain and audience. Do not deploy an older
full-site build over the live Fragment Room or music changes.

Apply `tools/patch_live_chat_delivery.mjs` to those patched modules before upload
to include the save-before-generation correction and safe failure notices. Its
`tools/validate_live_chat_delivery.mjs` checks the actual patched handler against
mocked successful and rejected model requests, including retained participant
messages, failed reply status, action confirmation, and audio boundaries.

Setting `HYPHA_CHAT_PROVIDER=gemini` selects the original dialogue transport.
Plate generation uses its own fixed OpenAI image configuration, described below.

## Existing encrypted fax images

The live Statement Clock already exposes generated plates inside Hypha Chat.
`tools/patch_live_images.mjs` replaces its expired Gemini image transport using
`worker/lib/low-cost-image.ts`. Apply it to a freshly downloaded live module
directory, after the earlier dialogue patches. Preserve all existing modules,
bindings, assets and Durable Object exports during upload.

The image request is fixed on the server:

| Setting | Value |
| --- | --- |
| API | Direct Images API, without an extra dialogue-model request |
| Model | `gpt-image-2.6-flare` |
| Quality | `high` |
| Dimensions | `1536x864`, retaining the existing 16:9 presentation |
| Format | JPEG at compression setting 100 |
| Count | One image per exposure |
| Timeout | 150 seconds |
| Retry or provider fallback | None |

Keep the existing six successful plates per user in a rolling 24-hour window,
duplicate checks, room prompts, clock identity, encrypted carrier, fax overlay,
and previously stored plates. Image output is not deterministic: the existing
Flow Seed identifies the clock statement, rather than seeding the OpenAI model.
The `era-v2` marker remains for compatibility with existing plate filters.
The pinned client receives only provider disclosure corrections and removal of
an inaccurate deterministic-image tooltip; no fax rendering code is changed.

The official image calculator estimates about $0.03234 in output per high-quality
1536x864 Flare image, plus prompt input at $5 per million tokens. Six images are
about $0.194 in image output, plus prompts. These are estimates, not a monetary
ceiling: the per-user limit is shared-site behavior and does not cap total site
spend across users. Preserve the existing API balance and leave paid auto-recharge
off. This change makes no credit purchases or billing-setting changes.

- [Image generation and cost calculator](https://developers.openai.com/api/docs/guides/image-generation)
- [GPT-Image-2.6 Flare](https://developers.openai.com/api/docs/models/gpt-image-2.6-flare)
- [Image request schema](https://developers.openai.com/api/reference/resources/images/methods/generate)

API credit availability and image-model access must still be verified in the
credited organization. Image access may require organization verification.
Configuration-only health checks do not establish either condition. Provider
failures expose a safe notice, without saving a partial image or silently trying
another paid request. JPEG output and response sizes are bounded to fit the
existing D1 row. The existing quota counts saved plates, so an unsuccessful
generation can incur provider costs without consuming a saved-plate slot.

## Python web service and Discord

For the optional Python web service, use the same provider, key, model and privacy
settings, plus `WEB_HYPHA_CHAT_ENABLED=true` and `OPENAI_DRY_RUN=false`. Its signed
relay URL/secret configuration is unchanged. `web-game.env.example` lists the
settings; it is not loaded automatically.

For Discord, the existing chat enablement flags retain their names:
`FEATURE_GEMINI_CHAT` and `FEATURE_GEMINI_DISCORD_CHAT`. Their selected transport
now follows `HYPHA_CHAT_PROVIDER`. OpenAI chat requires `OPENAI_ENABLED=true` or
`OPENAI_DRY_RUN=true`; live API use also requires the key and privacy setting.
Other OpenAI feature flags and defaults are unchanged. Gemini stays the default
until the OpenAI provider is explicitly selected.

## Checks

```sh
python -m pytest tests/test_openai_chat.py tests/test_hypha_transport.py tests/test_gemini_chat.py tests/test_gemini_config.py tests/test_web_game.py
cd activity
npm run validate:openai-chat
npm run validate:preview-chat
npm run validate:guest-demo
node tools/validate_low_cost_image.mjs
node tools/validate_live_images.mjs /absolute/path/to/patched/modules
npx tsc --noEmit
```

The automated checks use mocked API responses and do not consume paid inference.
Use `node tools/validate_live_openai.mjs /absolute/path/to/patched/modules` to
check the patched live module with mocked network responses before deployment.
