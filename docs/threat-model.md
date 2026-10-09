# Threat model

## Protected assets

- Discord and OpenAI credentials;
- deterministic live/test state and environment isolation;
- unrevealed puzzle facts and measurements;
- versioned public records and the distinction between historical, current, forecast,
  conditional, obsolete, and unresolved claims;
- remediation safety invariants, including source reduction, evidence, compatibility, capacity,
  containment, and spent-substrate custody;
- API budget and availability;
- the public-only interaction guarantee.

## Trust boundaries

Discord message content, display names, mentions, replies, and model output are untrusted. Numeric
guild/channel/role/user IDs from configuration, loaded puzzle definitions, environment/session
references, confirmed stored observations, and ordinary Python validators are trusted only after
their existing validation boundaries.

The OpenAI API receives a bounded current-position projection, not repository state or channel
history. Discord metadata is removed, people receive request-local `participant_N` labels, and the
sanitized current response is placed in a quoted untrusted-data block. A final pre-transport check
fails closed on residual Discord metadata. Structured output is parsed by Pydantic and checked
against current allowed actions, confirmed fact keys, public identifiers, proposal IDs, and
confidence before it can be offered to the deterministic engine. The engine alone can write
progression events.

## Principal abuse cases

- **Prompt injection or rule alteration:** deterministic phrase screening plus an explicit model
  flag; structured candidates still cannot encode rules or facts.
- **Invented state or IDs:** evidence and identifiers must be allowlisted from the selected
  environment; the engine independently checks all semantics and resources.
- **Greenwashing or remediation bypass:** a proposal cannot count treatment capacity in place of
  feasible source reduction. Unknown or incompatible discharge, low viability, saturation,
  excessive throughput, missing separation, insufficient containment, and visual-only evidence
  all fail closed through deterministic rules.
- **False safety claims:** returned water is not assumed usable, reduced color/odor/turbidity does
  not establish safety, and spent fungal substrate is never treated as compost by default.
  Sampling, auditing, reuse, and containment accept only configured public entities, measures,
  records, observations, destinations, and confirmed conditions.
- **Unsafe real-world remediation advice:** content uses broad fictional contaminant categories
  and categorical limits. Static narration and operator/player documentation prohibit culturing
  steps, exposure thresholds, chemical recipes, species-specific safety claims, and handling
  instructions for real contaminated material.
- **Untrusted record references:** free-text proposal and documentation fields cannot create
  evidence by assertion. Validators match required claims, observations, samples, record types,
  public needs, and handling references against confirmed public state and configured
  vocabularies.
- **Cross-environment leakage:** every context, cooldown, usage record, event, and state query
  requires a matching `SessionRef`; test identity is supplied only for test context.
- **Map over-reveal:** generic orientation is handled locally before the API and cannot unlock an
  observation or contribution.
- **Cost exhaustion:** deterministic relevance gating, prompt/output ceilings, persistent
  cooldowns, environment-scoped ledgers, soft warnings, and hard caps.
- **Provider outage, timeout, refusal, or malformed output:** fail closed without mutation and
  direct participants to explicit deterministic commands.
- **Missing privacy configuration or residual Discord identity:** network transport is not created
  without the explicit enable flag, API key, and privacy acknowledgement; the final payload check
  runs immediately before the API call and failure sends nothing.
- **Prompt or response persistence:** participant messages, prompts, and raw API responses are
  memory-only; migration `0003_privacy` drops the former prompt-context table.
- **Narration fact invention:** the canonical engine outcome is never sent to the model and is
  inserted locally after validation; the model can return only a lead and closing checked against
  a non-factual profile allowlist. Failure returns deterministic text and cannot change game state.
- **Narration environment leakage:** request construction uses the current durable `SessionRef` and
  includes no prior history; test and live usage and public narration histories remain separate.
- **Unauthorized surfaces:** DMs and nonconfigured guilds/channels are silent; test is configured
  administrators only; live requires administrator or mycotroph role and a running session.
- **Unbounded response loops:** only one public stack is open, it has at most four entries, each
  participant may add one entry, and resolution creates no nested interrupt window. Triggers are
  explicit single-use public records and cannot recursively alter rules.
- **Contribution or evidence farming:** equivalent samples, containment states, inoculations,
  reductions, failures, and other keyed actions are deduplicated. Repetition may return public
  guidance but cannot repeatedly increment counters or contribution credit.
- **Unsafe public launch:** live cannot leave locked mode through the launch command until content,
  database, clean-test, pristine-live, API-budget, and backup checks all pass and an administrator
  confirms in the configured live channel.
- **Operational state disclosure:** detailed state and export commands work only for configured
  administrators in the separate diagnostic channel; debug output reports counts and identifiers,
  not unrevealed measurements.
- **Malformed recovery:** rollback/invalidation use environment-scoped IDs, require a paused
  session, append audit events, preserve history, and rebuild projections. Retry accepts only the
  original validated typed action and only after invalidation.
- **Content-version erasure:** Provision Works upgrades are additive and environment-scoped. They
  preserve existing JSON progress and history while adding defaults, and record an idempotent
  audit event. Operators back up before content releases and roll code/content back as a matched
  release instead of treating an additive content upgrade as a reversible schema downgrade.
- **Deleted Discord content:** raw deletion events never remove durable game events; operators get
  an operational alert without message contents.

Residual risks include imperfect keyword injection detection, model misclassification that is
semantically valid but unintended, pricing configuration drift, and one-request budget overshoot.
These are bounded by deterministic validation, configurable confidence/cost controls, audit
records, environment-scoped recovery, and the always-available explicit-command path.
