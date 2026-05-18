# =========================================================================
# P5.M10 post-deploy probe -- Workshop Dashboard ACL verification.
#
# Verifies the dashboard's two HTTP entry paths reject crew + non-Neon
# users and accept manager + crew_leader. Catches hotfix regressions
# that the in-process smoke cannot reach (the menu-click path through
# ir.actions.server.run() has its own access checks separate from the
# get_dashboard_data RPC guard).
#
# Run AFTER:
#   1. docker compose run --rm odoo odoo -u neon_jobs -d <db> --stop-after-init
#   2. docker compose up -d --force-recreate odoo   <- the step that's
#                                                      easy to forget
#
# Usage:
#   pwsh ./.claude/probes/probe_workshop_dashboard.ps1
#   pwsh ./.claude/probes/probe_workshop_dashboard.ps1 -BaseUrl http://...
#
# Exit codes:
#   0 -- all 8 probes PASS
#   1 -- at least one probe FAIL (diagnostic table printed)
#
# Expected matrix:
#   Tier   | get_dashboard_data RPC | ir.actions.server.run()
#   -----  | ---------------------- | -----------------------
#   mgr    | returns dict           | returns client action
#   lead   | returns dict           | returns client action
#   crew   | AccessError            | AccessError
#   other  | AccessError            | AccessError
# =========================================================================

[CmdletBinding()]
param(
    [string]$BaseUrl = "http://localhost:8069",
    [string]$Database = "neon_crm",
    [string]$Password = "test123",
    [string]$ServerActionXmlId = "neon_jobs.action_workshop_dashboard_server"
)

$ErrorActionPreference = "Stop"

# -------------------------------------------------------------------------
# Tier matrix -- each row encodes the login and the expected outcome on
# each of the two HTTP paths. "data" = JSON response carries .result.
# "deny" = JSON response carries an AccessError in .error.
# -------------------------------------------------------------------------
$Tiers = @(
    [pscustomobject]@{ Login = "p2m75_mgr";   ExpectRpc = "data"; ExpectRun = "data" }
    [pscustomobject]@{ Login = "p2m75_lead";  ExpectRpc = "data"; ExpectRun = "data" }
    [pscustomobject]@{ Login = "p2m75_crew";  ExpectRpc = "deny"; ExpectRun = "deny" }
    [pscustomobject]@{ Login = "p2m75_other"; ExpectRpc = "deny"; ExpectRun = "deny" }
)

# -------------------------------------------------------------------------
# Result accumulator -- table rows printed at the end.
# -------------------------------------------------------------------------
$Results = New-Object 'System.Collections.Generic.List[object]'

function Add-Result {
    param([string]$Login, [string]$Path, [string]$Expect, [string]$Actual, [string]$Detail)
    $pass = ($Expect -eq $Actual)
    $Results.Add([pscustomobject]@{
        Tier   = $Login
        Path   = $Path
        Expect = $Expect
        Actual = $Actual
        Pass   = $pass
        Detail = $Detail
    })
}

# -------------------------------------------------------------------------
# /web/session/authenticate returns the uid and binds the session cookie
# to $Session. Returns $null on auth failure (probed login does not exist
# or wrong password).
# -------------------------------------------------------------------------
function Invoke-Auth {
    param([string]$Login, [Parameter()][ref]$Session)
    $body = @{
        jsonrpc = "2.0"; method = "call"
        params  = @{ db = $Database; login = $Login; password = $Password }
    } | ConvertTo-Json -Depth 5
    try {
        $r = Invoke-WebRequest -Uri "$BaseUrl/web/session/authenticate" `
            -Method Post -ContentType "application/json" -Body $body `
            -SessionVariable s -UseBasicParsing
    } catch {
        return $null
    }
    $resp = ($r.Content | ConvertFrom-Json)
    if (-not $resp.result.uid) { return $null }
    $Session.Value = $s
    return [int]$resp.result.uid
}

# -------------------------------------------------------------------------
# Classify a /web/dataset/call_kw or /web/dataset/call_button response.
# Returns one of:
#   "data" -- has .result, no .error
#   "deny" -- has .error with data.name = odoo.exceptions.AccessError
#   "fail" -- anything else (unexpected error, transport failure)
# -------------------------------------------------------------------------
function Classify-Response {
    param($Content)
    if (-not $Content) { return @{ kind = "fail"; detail = "empty body" } }
    $parsed = $Content | ConvertFrom-Json
    if ($parsed.error) {
        if ($parsed.error.data.name -eq "odoo.exceptions.AccessError") {
            return @{ kind = "deny"; detail = "AccessError: $($parsed.error.data.message -replace '\r?\n',' ')" }
        }
        return @{ kind = "fail"; detail = "Unexpected: $($parsed.error.data.name) -- $($parsed.error.data.message -replace '\r?\n',' ')" }
    }
    if ($null -ne $parsed.result) {
        return @{ kind = "data"; detail = "result type=$($parsed.result.type)" }
    }
    return @{ kind = "fail"; detail = "no .result and no .error" }
}

# -------------------------------------------------------------------------
# Per-tier probe sequence.
# -------------------------------------------------------------------------
Write-Output ("=" * 72)
Write-Output "Workshop Dashboard post-deploy probe  ($BaseUrl, db=$Database)"
Write-Output ("=" * 72)

foreach ($tier in $Tiers) {
    $session = $null
    $uid = Invoke-Auth -Login $tier.Login -Session ([ref]$session)
    if (-not $uid) {
        Add-Result $tier.Login "auth" "ok" "fail" "Authenticate returned no uid (seed user missing or wrong password?)"
        continue
    }
    Write-Output ""
    Write-Output ("[" + $tier.Login + "]  uid=$uid")

    # Path 1: direct /web/dataset/call_kw on get_dashboard_data
    $rpcBody = @{
        jsonrpc = "2.0"; method = "call"
        params  = @{
            model = "neon.equipment.dashboard"
            method = "get_dashboard_data"
            args = @(); kwargs = @{}
        }
    } | ConvertTo-Json -Depth 6
    try {
        $r1 = Invoke-WebRequest -Uri "$BaseUrl/web/dataset/call_kw" `
            -Method Post -ContentType "application/json" -Body $rpcBody `
            -WebSession $session -UseBasicParsing
        $c1 = Classify-Response $r1.Content
    } catch {
        $c1 = @{ kind = "fail"; detail = "HTTP exception: $($_.Exception.Message)" }
    }
    Add-Result $tier.Login "get_dashboard_data" $tier.ExpectRpc $c1.kind $c1.detail
    Write-Output ("    get_dashboard_data:  expect=" + $tier.ExpectRpc + "  actual=" + $c1.kind + "   " + $c1.detail)

    # Path 2: resolve server action xml_id via /web/action/load
    # (same endpoint the web client uses; accepts xml_id strings)
    # then call ir.actions.server.run() on the resolved id.
    $idBody = @{
        jsonrpc = "2.0"; method = "call"
        params  = @{ action_id = $ServerActionXmlId }
    } | ConvertTo-Json -Depth 6
    try {
        $r2 = Invoke-WebRequest -Uri "$BaseUrl/web/action/load" `
            -Method Post -ContentType "application/json" -Body $idBody `
            -WebSession $session -UseBasicParsing
        $idResp = ($r2.Content | ConvertFrom-Json)
        if ($idResp.result -and $idResp.result.id) {
            $serverActionId = [int]$idResp.result.id
        } else {
            $serverActionId = $null
        }
    } catch {
        $serverActionId = $null
    }
    if (-not $serverActionId) {
        Add-Result $tier.Login "server_action.run" $tier.ExpectRun "fail" "Could not resolve $ServerActionXmlId -- is the action installed?"
        Write-Output ("    server_action.run:   expect=" + $tier.ExpectRun + "  actual=fail   xmlid resolution failed")
        continue
    }
    $runBody = @{
        jsonrpc = "2.0"; method = "call"
        params  = @{
            model = "ir.actions.server"; method = "run"
            args = @(@($serverActionId))
            kwargs = @{ context = @{
                active_id = $serverActionId
                active_model = "ir.actions.server"
            } }
        }
    } | ConvertTo-Json -Depth 6
    try {
        $r3 = Invoke-WebRequest -Uri "$BaseUrl/web/dataset/call_kw" `
            -Method Post -ContentType "application/json" -Body $runBody `
            -WebSession $session -UseBasicParsing
        $c3 = Classify-Response $r3.Content
    } catch {
        $c3 = @{ kind = "fail"; detail = "HTTP exception: $($_.Exception.Message)" }
    }
    Add-Result $tier.Login "server_action.run" $tier.ExpectRun $c3.kind $c3.detail
    Write-Output ("    server_action.run:   expect=" + $tier.ExpectRun + "  actual=" + $c3.kind + "   " + $c3.detail)
}

# -------------------------------------------------------------------------
# Summary table + exit code.
# -------------------------------------------------------------------------
Write-Output ""
Write-Output ("=" * 72)
Write-Output "SUMMARY"
Write-Output ("=" * 72)
$Results | Format-Table -AutoSize -Property Tier, Path, Expect, Actual,
    @{ Name = "Mark"; Expression = { if ($_.Pass) { "PASS" } else { "FAIL" } } }

$failed = @($Results | Where-Object { -not $_.Pass })
if ($failed.Count -gt 0) {
    Write-Output ""
    Write-Output "FAILED ($($failed.Count)):"
    foreach ($f in $failed) {
        Write-Output ("  - [" + $f.Tier + "] " + $f.Path + ":  " + $f.Detail)
    }
    exit 1
}
Write-Output ""
Write-Output "All 8 probes PASSED."
exit 0
