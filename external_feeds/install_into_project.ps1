param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"

$Source = Join-Path $PSScriptRoot "src\uniflora\external_feeds\aprsfi"
$ParentSource = Join-Path $PSScriptRoot "src\uniflora\external_feeds\__init__.py"
$DestinationParent = Join-Path $ProjectRoot "src\uniflora\external_feeds"
$Destination = Join-Path $DestinationParent "aprsfi"

New-Item -ItemType Directory -Force -Path $Destination | Out-Null
Copy-Item -Path (Join-Path $Source "*") -Destination $Destination -Recurse -Force

if (-not (Test-Path (Join-Path $DestinationParent "__init__.py"))) {
    Copy-Item -Path $ParentSource -Destination $DestinationParent -Force
}

Write-Host "Installed aprs.fi integration to:"
Write-Host "  $Destination"
Write-Host ""

$PythonFiles = Get-ChildItem $Destination -Filter "*.py" | ForEach-Object FullName
& python -m py_compile $PythonFiles

if ($LASTEXITCODE -ne 0) {
    throw "Python compile check failed."
}

Write-Host "Compile check passed."
Write-Host ""
Write-Host "Next steps:"
Write-Host "1. Edit $Destination\targets.json"
Write-Host "2. Set the APRSFI environment variables"
Write-Host "3. Review hypha_integration_example.py"
