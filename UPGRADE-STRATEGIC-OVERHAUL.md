# Installing the strategic overhaul

Use the packaged `Apply-Strategic-Overhaul.ps1`; do not copy the overlay by
hand. Stop Hypha first. The installer validates hashes and the stochastic
baseline, creates a complete timestamped source backup, copies only manifest
files, compiles changed Python, runs replay/campaign tests, and rolls back on a
required failure.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
    -File ".\Apply-Strategic-Overhaul.ps1" `
    -ProjectRoot "C:\path\to\uniflora" `
    -RunActivityCheck
```

The default is fail-closed when a destination differs from the reviewed
baseline. Review every reported path before using `-AllowDivergedBaseline`.
That switch preserves backups but necessarily replaces the listed diverged
files with the reviewed overlay.

The event database is not migrated or copied. The first accepted strategic
operation lazily initializes schema-4 board state on an existing stream.
