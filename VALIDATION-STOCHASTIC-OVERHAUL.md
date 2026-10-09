# Stochastic overhaul validation report

## Completed checks

### Python compilation

All active Python modules changed by the overhaul, both validation scripts, and the new focused tests compile successfully. Historical `before-*` and `broken-backup` files already present in the source snapshot are intentionally excluded.

### Focused engine and transport suite

The following test groups pass together:

- stochastic overhaul tests;
- v2 content validation;
- investigation kernel;
- events and replay;
- serialization;
- persistent application service;
- text transport;
- transport facade.

Result at packaging time: **76 passed**.

### Complete campaign verification

The real command/kernel/event/reducer path was executed from Position 0 through the ending using both route families.

- Primary routes: PASS, final sequence 158.
- Alternate routes: PASS, final sequence 167.
- All six positions completed.
- Every position recorded stochastic observations.
- Final event stream replay matched authoritative state exactly.

The verifier is in-memory and does not touch the live database.

### Stochastic balance audit

A content-driven audit ran seeded chains across all six processes and checked:

- transition reachability;
- observation-channel coverage;
- latent-state occupancy;
- non-collapsed model support;
- model-support normalization;
- completion-route references.

The audited process and route structure passed.

### Public runtime

A real public Discord identity was joined into a temporary SQLite stream. The test began the investigation, examined evidence, assigned a custom role, resolved a stochastic capability, and received a non-null rich transport response.

### Activity TypeScript contract

The Activity TypeScript project passes `tsc --noEmit`. Public-state validation supports schema versions 2.0 through 2.3 and remains closed-key validated.

## Environmental limitations of the packaging container

The complete legacy test collection includes modules requiring `discord.py` and `hypothesis`, which were unavailable in the packaging container. The remaining old content tests also contain assumptions tied to earlier linear pack versions and are not authoritative for the new `1.1.0-stochastic-overhaul` content contract.

A full Vite bundle was not produced in the Linux packaging container because the source snapshot’s `node_modules` came from Windows and lacked the Linux-native Rolldown binding. The TypeScript compiler passed. Run `npm ci` and `npm run check` on the Windows project to validate the native frontend toolchain.

## Required operator acceptance

After installation, confirm the live sequence-9 stream loads before performing another command. Then execute one Position 1 stochastic capability and verify that:

- sequence advances once;
- the event contains a stochastic resolution;
- replay remains valid;
- the public Activity omits latent state and Discord IDs;
- route progress and model support update within the Activity refresh interval.
