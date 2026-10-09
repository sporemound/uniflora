# Installing the stochastic overhaul

The supplied installer applies a reviewed overlay to an existing Missing Interior source tree. It does not replace the repository wholesale.

## Before installation

Stop Hypha so no process is holding the v2 SQLite event store.

From PowerShell:

```powershell
Set-Location "C:\path\to\uniflora"
Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and
        $_.CommandLine -match 'uniflora|missing-interior'
    } |
    Select-Object ProcessId, Name, CommandLine |
    Format-List
```

Stop only the relevant Hypha process before applying the overlay.

## Install

Extract `missing-interior-stochastic-overhaul.zip`, open PowerShell in the extracted folder, and run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
    -File ".\Apply-Overhaul.ps1" `
    -ProjectRoot "C:\path\to\uniflora"
```

The installer:

- validates its own file hashes;
- verifies the target repository shape;
- creates a timestamped backup under `backups\stochastic-overhaul-*`;
- records whether each destination existed before installation;
- copies only the changed and new overhaul files;
- compiles the Python package;
- validates the content pack;
- runs both complete campaign route verifiers;
- rolls the overlay back automatically if required verification fails.

It does not copy or modify:

- `.env`;
- `.dev.vars`;
- Discord or Activity secrets;
- SQLite databases;
- `node_modules`;
- generated scientific bundles;
- unrelated files elsewhere in the repository.

## Activity validation

The installer performs Python verification by default. To also run the Activity check when Node dependencies are installed:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
    -File ".\Apply-Overhaul.ps1" `
    -ProjectRoot "C:\path\to\uniflora" `
    -RunActivityCheck
```

If the Activity dependencies are not installed or were copied from a different operating system, run this from the project afterward:

```powershell
Set-Location "C:\path\to\uniflora\activity"
npm ci
npm run check
```

## Current stream compatibility

The existing Position 1 stream may continue. No database migration or reset is required. Existing event identifiers and schema-2 serialization remain supported.

Before restarting Hypha, you may create an additional manual SQLite backup:

```powershell
$Root = "C:\path\to\uniflora"
$Source = Join-Path $Root "data\v2-test-events.sqlite3"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Destination = Join-Path $Root "backups\v2-before-stochastic-overhaul-$Stamp.sqlite3"

New-Item -ItemType Directory -Force -Path (Split-Path $Destination) | Out-Null
Copy-Item -LiteralPath $Source -Destination $Destination
$Destination
```

## Restart and acceptance

Restart Hypha using the project’s existing launch command. Then verify:

1. `/v2 status` returns the current sequence and player state.
2. `/v2 guide` displays completion routes and live blockers.
3. A valid stochastic capability returns a structured observation rather than a fixed canned result.
4. The Discord response reports that the Activity projection was published or already current.
5. The Activity updates sequence, phase, routes, evidence, capability status, recent observations, and model support.

## Rollback

The successful installer prints the exact backup directory. To restore it:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
    -File ".\Rollback-Overhaul.ps1" `
    -ProjectRoot "C:\path\to\uniflora" `
    -BackupPath "C:\path\to\uniflora\backups\stochastic-overhaul-YYYYMMDD-HHMMSS"
```

Rollback restores every pre-existing file from the backup and removes files that the overhaul created new. It does not alter the event database.
