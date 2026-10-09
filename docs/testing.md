# Testing and acceptance checks

Install the development dependencies in the active Python 3.11+ environment:

```powershell
python -m pip install -e ".[dev]"
```

Run the complete offline acceptance suite from the repository root:

```powershell
ruff format --check .
ruff check .
pytest -q
python -m compileall -q src tests migrations
alembic heads
```

The suite uses temporary SQLite databases and fake providers. It does not require a Discord
token, OpenAI key, PostgreSQL service, or network connection. It covers authorization, live/test
isolation, deterministic Positions 0-6 completion, sustainability, circulation, translation, the
Provision Works arc, participant separation, idempotency, restart recovery, imports and rollback,
YAML/framework validation, orientation limits, malformed or hostile model output, API fallback
and budget controls, and narration fact preservation.

For a faster content-only pass:

```powershell
pytest -q tests/test_content.py tests/test_provision_arc.py
```

`/interior validate-content` performs the production-side equivalent of strict YAML loading,
fallback narration-key validation, complete Position 0-6 framework coverage, and an isolated
slash-only simulation from Position 0 through terminal Position 6. The simulation checks the
three-person Position 0 path, four-person Position 1 path, translation, producer reciprocity, the
ordered maintenance cycle, versioned memory, four-participant reconstruction, terminal
read-only behavior, and test/live isolation. It uses an in-memory database and does not mutate
either durable session.

## Provision Works regression coverage

`tests/test_provision_arc.py` and `tests/test_content.py` protect the arc's non-negotiable rules:

- remediation cannot substitute for required source reduction;
- unknown or incompatible discharge fails safely, and low viability, saturation, or excessive
  throughput prevents successful treatment;
- visual clarity does not add safety evidence, returned water is not assumed usable, and spent
  substrate requires approved containment;
- public benefit does not erase local burden;
- repeated samples or containment actions cannot farm evidence or contribution credit;
- failures preserve useful public state instead of resetting the position;
- proposals retain participant/function thresholds and non-author confirmation;
- final reconstruction reduces unnecessary throughput, protects livelihoods or supplies a
  transition, and includes public governance and ecological limits; and
- the complete arc remains isolated from live state when exercised in test.

When a content rule, counter, proposal field, action, or entity reference changes, run both of
those modules and then the complete suite. A passing unit test for one validator branch is not a
substitute for the end-to-end packaged-content simulation.

## Credentialed smoke test

The offline suite cannot prove Discord permissions, command synchronization, provider
connectivity, or host-specific PostgreSQL backup behavior. In a private administrator-only test
surface:

1. Start with `OPENAI_ENABLED=false`, confirm `/healthz` and `/readyz`, and run `/interior ops setup`.
2. Complete a clean test run through Positions 0-6. Use at least three simulated identities for
   the early positions and four distinct identities/functions for final reconstruction.
3. Exercise checkpoint/export/import while paused and verify live remains locked and pristine.
4. If OpenAI is desired, first run `OPENAI_DRY_RUN=true` locally with fictional responses and
   inspect the sanitized payload. Do not use real participant responses as test data. Activation is
   a separate authorized step documented in `openai-setup.md`; after authorization, use a low test
   budget and verify deterministic fallback by turning `/interior test gpt-off` on and off.
5. On PostgreSQL hosting, run and restore one `pg_dump` backup outside the production database.
6. Exercise at least one safe failure in the remediation cycle and verify that the public failure
   record remains useful without resetting progress.
7. Run `validate-content` and `live-readiness`; do not use `start-live` until every check passes.

Never use the production channel as a development sandbox, and never place real credentials in
test output, fixtures, screenshots, or issue reports.
