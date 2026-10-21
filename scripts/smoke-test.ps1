<#
.SYNOPSIS
  End-to-end smoke test against a running InfraScope API.

.DESCRIPTION
  Registers a target pointing at /unhealthy, waits for an incident, re-points it at
  /healthy, waits for resolution, and prints the stored results. Optionally restarts
  the Compose stack and confirms the data survived. Needs an ADMIN API key.

.EXAMPLE
  $env:INFRASCOPE_API_KEY = "isk_..."              # an ADMIN key
  .\scripts\smoke-test.ps1                          # against Docker Compose
  .\scripts\smoke-test.ps1 -VerifyRestart           # also restarts containers
  .\scripts\smoke-test.ps1 -TargetBase http://localhost:8081   # local (non-Docker) run
#>
param(
    [string]$Api = "http://127.0.0.1:8000",
    [string]$TargetBase = "http://testtarget:8080",
    [int]$IntervalSeconds = 5,
    [string]$ApiKey = $env:INFRASCOPE_API_KEY,
    [switch]$VerifyRestart
)

$ErrorActionPreference = "Stop"
if (-not $ApiKey) {
    throw "No API key. Set `$env:INFRASCOPE_API_KEY or pass -ApiKey (create one with: docker compose exec api python -m app.cli create-api-key --name smoke --role ADMIN)"
}
$Headers = @{ "X-API-Key" = $ApiKey }

function Invoke-Api([string]$Method, [string]$Path, $Body = $null) {
    $params = @{ Method = $Method; Uri = "$Api$Path"; Headers = $Headers }
    if ($null -ne $Body) {
        $params.ContentType = "application/json"
        $params.Body = $Body | ConvertTo-Json
    }
    return Invoke-RestMethod @params
}

# Windows PowerShell 5.1 emits a JSON array as ONE pipeline object; unroll it.
function Get-List([string]$Path) {
    # The leading comma stops PowerShell unrolling a one-element array on return.
    return , @(Invoke-Api GET $Path | ForEach-Object { $_ })
}

function Wait-Until([scriptblock]$Condition, [int]$TimeoutSeconds, [string]$What) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Condition) { Write-Host "  OK: $What"; return }
        Start-Sleep -Seconds 1
    }
    throw "Timed out waiting for: $What"
}

Write-Host "1. Health check and key"
$health = Invoke-RestMethod "$Api/health"
$health | Format-List
if ($health.database -ne "ok") { throw "Database is not healthy" }
$me = Invoke-Api GET "/api/v1/auth/me"
Write-Host "  using key '$($me.name)' ($($me.key_prefix)..., role $($me.role))"
if ($me.role -ne "ADMIN") { throw "The smoke test needs an ADMIN key" }

Write-Host "2. Register target -> $TargetBase/unhealthy"
$name = "smoke-" + (Get-Date -Format "HHmmss")
# A per-run query string keeps the URL unique, so the script can be re-run.
$target = Invoke-Api POST "/api/v1/targets" @{ name = $name; url = "$TargetBase/unhealthy?run=$name"; interval_seconds = $IntervalSeconds }
Write-Host "  id=$($target.id)"

Write-Host "3. Wait for DOWN + OPEN incident (2 failed checks)"
Wait-Until { (Invoke-Api GET "/api/v1/targets/$($target.id)").status -eq "DOWN" } ($IntervalSeconds * 4) "target DOWN"
$open = Get-List "/api/v1/incidents?target_id=$($target.id)&status=OPEN"
if ($open.Count -ne 1) { throw "Expected exactly 1 open incident, got $($open.Count)" }
Write-Host "  incident opened_at=$($open[0].opened_at) reason=$($open[0].failure_reason)"

Write-Host "4. Re-point target at /healthy and wait for resolution (2 successful checks)"
Invoke-Api PATCH "/api/v1/targets/$($target.id)" @{ url = "$TargetBase/healthy?run=$name" } | Out-Null
Wait-Until { (Invoke-Api GET "/api/v1/targets/$($target.id)").status -eq "UP" } ($IntervalSeconds * 4) "target UP"
$incidents = Get-List "/api/v1/incidents?target_id=$($target.id)"
if ($incidents.Count -ne 1) { throw "Expected exactly 1 incident, got $($incidents.Count)" }
$incident = $incidents[0]
if ($incident.status -ne "RESOLVED") { throw "Incident not resolved" }
Write-Host "  incident resolved_at=$($incident.resolved_at)"

$results = Get-List "/api/v1/targets/$($target.id)/results"
Write-Host "5. Stored results: $($results.Count)"
if ($results.Count -lt 4) { throw "Expected at least 4 stored results" }
$results | Select-Object checked_at, success, status_code, response_time_ms, error | Format-Table

if ($VerifyRestart) {
    Write-Host "6. Restarting containers (docker compose restart) to verify persistence"
    # docker prints progress on stderr, which PowerShell 5.1 turns into a terminating
    # error under ErrorActionPreference=Stop; rely on the exit code instead.
    $ErrorActionPreference = "Continue"
    docker compose restart api db 2>&1 | ForEach-Object { Write-Host "  $_" }
    $restartExit = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($restartExit -ne 0) { throw "docker compose restart failed (exit $restartExit)" }
    Wait-Until { try { (Invoke-RestMethod "$Api/health").database -eq "ok" } catch { $false } } 90 "API healthy after restart"
    $after = Get-List "/api/v1/targets/$($target.id)/results?limit=1000"
    if ($after.Count -lt $results.Count) { throw "Results lost after restart" }
    Write-Host "  OK: $($after.Count) results present after restart (was $($results.Count))"
}

Write-Host "`nSmoke test PASSED" -ForegroundColor Green
