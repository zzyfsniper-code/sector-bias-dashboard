param(
    [string]$AsOf
)

$ErrorActionPreference = 'Stop'

$strategyDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$latestPath = Join-Path $strategyDir 'logs\daily\latest.json'
$pageUrl = 'https://zzyfsniper-code.github.io/sector-bias-dashboard/all-weather-risk-parity/'
$centerUrl = 'https://zzyfsniper-code.github.io/sector-bias-dashboard/strategies/'
$workspaceRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $strategyDir))
$publisherCandidates = @(Get-ChildItem -LiteralPath $workspaceRoot -Filter 'publish_github_page.py' -File -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.FullName -like '*fund_flow_long_timing*' })
if ($publisherCandidates.Count -ne 1) { throw 'Scoped GitHub publisher was not uniquely located.' }
$publisher = $publisherCandidates[0].FullName

$token = [Environment]::GetEnvironmentVariable('TUSHARE_TOKEN', 'Process')
if ([string]::IsNullOrWhiteSpace($token)) { $token = [Environment]::GetEnvironmentVariable('TUSHARE_TOKEN', 'User') }
if ([string]::IsNullOrWhiteSpace($token)) { throw 'TUSHARE_TOKEN is not configured in the process or Windows user environment.' }
$env:TUSHARE_TOKEN = $token
$githubToken = [Environment]::GetEnvironmentVariable('GITHUB_TOKEN', 'Process')
if ([string]::IsNullOrWhiteSpace($githubToken)) { $githubToken = [Environment]::GetEnvironmentVariable('GITHUB_TOKEN', 'User') }
if ([string]::IsNullOrWhiteSpace($githubToken)) { throw 'GITHUB_TOKEN is not configured in the process or Windows user environment.' }
$env:GITHUB_TOKEN = $githubToken

foreach ($name in @('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy')) {
    Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
}

$dailyArguments = @((Join-Path $strategyDir 'daily_update.py'))
if (-not [string]::IsNullOrWhiteSpace($AsOf)) { $dailyArguments += @('--as-of', $AsOf) }
& py -3 @dailyArguments
if ($LASTEXITCODE -ne 0) { throw "Daily risk-parity update failed with exit code $LASTEXITCODE." }
if (-not (Test-Path -LiteralPath $latestPath)) { throw "Daily status file was not created: $latestPath" }
$latest = Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($latest.status -ne 'PASS' -or $latest.validation.status -ne 'PASS' -or [string]::IsNullOrWhiteSpace([string]$latest.run_id)) {
    throw 'Daily risk-parity status did not pass validation.'
}
if ($latest.data_quality.status -ne 'PASS' -or [string]::IsNullOrWhiteSpace([string]$latest.target_trade_date)) {
    throw 'Daily risk-parity data-quality validation did not pass.'
}

& py -3 $publisher --message "data: update all-weather risk parity $($latest.target_trade_date)"
if ($LASTEXITCODE -ne 0) { throw 'Failed to publish the strategy pages through the scoped GitHub API update.' }

$onlineVerified = $false
$onlineDataUrl = $pageUrl + 'data/strategy-data.js?run=' + [uri]::EscapeDataString([string]$latest.run_id)
for ($attempt = 1; $attempt -le 6; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri $onlineDataUrl -UseBasicParsing -TimeoutSec 30
        $center = Invoke-WebRequest -Uri $centerUrl -UseBasicParsing -TimeoutSec 30
        if ($response.StatusCode -eq 200 -and $response.Content.Contains([string]$latest.run_id) -and $center.StatusCode -eq 200) {
            $onlineVerified = $true
            break
        }
    } catch {
        if ($attempt -eq 6) { break }
    }
    Start-Sleep -Seconds 10
}
if (-not $onlineVerified) { throw "GitHub Pages did not expose run $($latest.run_id) within the verification window." }

$latest.publish.git_status = 'PUSHED_SCOPED'
$latest.publish.online_status = 'PASS'
$latest.publish | Add-Member -NotePropertyName url -NotePropertyValue $pageUrl -Force
$latest.publish | Add-Member -NotePropertyName center_url -NotePropertyValue $centerUrl -Force
$latest.publish | Add-Member -NotePropertyName verified_run_id -NotePropertyValue ([string]$latest.run_id) -Force
$latest | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $latestPath -Encoding utf8
Write-Output ($latest | ConvertTo-Json -Depth 100 -Compress)
