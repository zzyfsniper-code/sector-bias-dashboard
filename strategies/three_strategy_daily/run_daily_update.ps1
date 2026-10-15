param(
    [string]$AsOf,
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$strategyDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $strategyDir 'logs\daily'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-NestedValue {
    param($Object, [string[]]$Path)
    $value = $Object
    foreach ($part in $Path) {
        if ($null -eq $value) { return $null }
        $property = $value.PSObject.Properties[$part]
        if ($null -eq $property) { return $null }
        $value = $property.Value
    }
    return $value
}

function Add-Failure {
    param([System.Collections.Generic.List[string]]$Failures, [bool]$Condition, [string]$Message)
    if (-not $Condition) { $Failures.Add($Message) | Out-Null }
}

function Test-CommonManifest {
    param($Manifest, [int]$ExitCode, [string]$OldRunId, [bool]$RequireNewRun, [bool]$RequirePublish)
    $failures = [System.Collections.Generic.List[string]]::new()
    Add-Failure $failures ($ExitCode -eq 0) "child exit_code=$ExitCode"
    Add-Failure $failures ($null -ne $Manifest) 'final latest.json is missing or invalid'
    if ($null -eq $Manifest) { return $failures.ToArray() }

    $runId = [string](Get-NestedValue $Manifest @('run_id'))
    Add-Failure $failures (-not [string]::IsNullOrWhiteSpace($runId)) 'run_id is empty'
    if ($RequireNewRun) {
        Add-Failure $failures ($runId -ne $OldRunId) "run_id did not change from $OldRunId"
    }
    Add-Failure $failures ((Get-NestedValue $Manifest @('status')) -eq 'PASS') 'top-level status is not PASS'
    Add-Failure $failures ((Get-NestedValue $Manifest @('validation', 'status')) -eq 'PASS') 'validation.status is not PASS'
    if ($RequirePublish) {
        Add-Failure $failures ((Get-NestedValue $Manifest @('publish', 'git_status')) -eq 'PUSHED_SCOPED') 'publish.git_status is not PUSHED_SCOPED'
        Add-Failure $failures ((Get-NestedValue $Manifest @('publish', 'online_status')) -eq 'PASS') 'publish.online_status is not PASS'
        Add-Failure $failures ((Get-NestedValue $Manifest @('publish', 'verified_run_id')) -eq $runId) 'publish.verified_run_id does not match run_id'
    }
    return $failures.ToArray()
}

function Test-GrowthManifest {
    param($Manifest)
    $failures = [System.Collections.Generic.List[string]]::new()
    if ($null -eq $Manifest) { return $failures.ToArray() }
    $target = [string](Get-NestedValue $Manifest @('target_trade_date'))
    Add-Failure $failures (-not [string]::IsNullOrWhiteSpace($target)) 'target_trade_date is empty'
    Add-Failure $failures ((Get-NestedValue $Manifest @('publish', 'copy_status')) -eq 'PASS') 'publish.copy_status is not PASS'

    $checks = Get-NestedValue $Manifest @('validation', 'checks')
    Add-Failure $failures ($null -ne $checks) 'validation.checks is missing'
    if ($null -ne $checks) {
        foreach ($property in $checks.PSObject.Properties) {
            Add-Failure $failures ([bool]$property.Value) "validation check failed: $($property.Name)"
        }
    }
    foreach ($code in @('399370.SZ', '399371.SZ')) {
        Add-Failure $failures ((Get-NestedValue $Manifest @('freshness', 'momentum', 'latest', $code)) -eq $target) "momentum $code did not reach $target"
    }
    Add-Failure $failures ((Get-NestedValue $Manifest @('freshness', 'breadth', 'latest')) -eq $target) "breadth did not reach $target"
    foreach ($code in @('399370.SZ', '399371.SZ', '881001.WI')) {
        Add-Failure $failures ((Get-NestedValue $Manifest @('freshness', 'crowding', 'latest', $code)) -eq $target) "crowding $code did not reach $target"
    }
    $growth = [double](Get-NestedValue $Manifest @('validation', 'trading_plan', 'targetGrowthWeight'))
    $value = [double](Get-NestedValue $Manifest @('validation', 'trading_plan', 'targetValueWeight'))
    Add-Failure $failures ([math]::Abs(($growth + $value) - 1.0) -lt 0.000001) 'growth/value target weights do not sum to 100%'
    return $failures.ToArray()
}

function Test-Csi500Manifest {
    param($Manifest)
    $failures = [System.Collections.Generic.List[string]]::new()
    if ($null -eq $Manifest) { return $failures.ToArray() }
    $target = [string](Get-NestedValue $Manifest @('target_trade_date'))
    Add-Failure $failures ((Get-NestedValue $Manifest @('data_quality', 'status')) -eq 'PASS') 'data_quality.status is not PASS'
    foreach ($field in @('moneyflow_date', 'index_date', 'etf_date')) {
        Add-Failure $failures ((Get-NestedValue $Manifest @('data_quality', $field)) -eq $target) "data_quality.$field did not reach $target"
    }
    $coverage = [double](Get-NestedValue $Manifest @('data_quality', 'member_coverage'))
    Add-Failure $failures ($coverage -ge 0.85) "member coverage is below 85%: $coverage"
    Add-Failure $failures ((Get-NestedValue $Manifest @('validation', 'frozen_reconciliation', 'status')) -eq 'PASS') 'frozen reconciliation is not PASS'
    foreach ($field in @('current_target', 'base_target', 'next_target')) {
        $value = [double](Get-NestedValue $Manifest @('trade', $field))
        Add-Failure $failures (@(0.0, 1.0, 2.0) -contains $value) "trade.$field is outside {0,1,2}: $value"
    }
    return $failures.ToArray()
}

function Test-RiskParityManifest {
    param($Manifest, [bool]$RequirePortfolio)
    $failures = [System.Collections.Generic.List[string]]::new()
    if ($null -eq $Manifest) { return $failures.ToArray() }
    $target = [string](Get-NestedValue $Manifest @('target_trade_date'))
    Add-Failure $failures ((Get-NestedValue $Manifest @('data_quality', 'status')) -eq 'PASS') 'data_quality.status is not PASS'
    Add-Failure $failures ((Get-NestedValue $Manifest @('data_quality', 'price_date')) -eq $target) "price data did not reach $target"
    Add-Failure $failures ([int](Get-NestedValue $Manifest @('data_quality', 'asset_count')) -eq 4) 'risk-parity asset count is not 4'
    Add-Failure $failures ([bool](Get-NestedValue $Manifest @('validation', 'no_future_price_in_signal'))) 'future-data isolation check failed'
    foreach ($version in @('base', 'levered_0', 'levered_3')) {
        foreach ($metric in @('cagr', 'max_drawdown', 'sharpe_zero_rf')) {
            Add-Failure $failures ($null -ne (Get-NestedValue $Manifest @('performance', $version, 'metrics', $metric))) "performance.$version.$metric is missing"
        }
    }
    Add-Failure $failures (-not [string]::IsNullOrWhiteSpace([string](Get-NestedValue $Manifest @('trade', 'next_signal_date')))) 'next signal date is missing'
    Add-Failure $failures (-not [string]::IsNullOrWhiteSpace([string](Get-NestedValue $Manifest @('trade', 'next_execution_date')))) 'next execution date is missing'
    if ($RequirePortfolio) {
        $assets = @(Get-NestedValue $Manifest @('portfolio', 'assets'))
        Add-Failure $failures ($assets.Count -eq 4) 'portfolio assets are missing from latest.json'
        if ($assets.Count -eq 4) {
            $weightSum = ($assets | Measure-Object -Property target_weight -Sum).Sum
            Add-Failure $failures ([math]::Abs([double]$weightSum - 1.0) -lt 0.000001) 'risk-parity target weights do not sum to 100%'
        }
    }
    return $failures.ToArray()
}

function Get-ErrorSummary {
    param([string]$StdoutPath, [string]$StderrPath)
    $text = ''
    foreach ($path in @($StdoutPath, $StderrPath)) {
        if (Test-Path -LiteralPath $path) {
            $bytes = [System.IO.File]::ReadAllBytes($path)
            try {
                $decoded = [System.Text.UTF8Encoding]::new($false, $true).GetString($bytes)
            } catch [System.Text.DecoderFallbackException] {
                $decoded = [System.Text.Encoding]::GetEncoding(936).GetString($bytes)
            }
            $text += "`n" + $decoded
        }
    }
    $text = $text -replace '(?i)(TUSHARE_TOKEN|GITHUB_TOKEN|WIND_TOKEN|BEARER)\s*[:=]\s*\S+', '$1=[REDACTED]'
    $lines = @($text -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($lines.Count -eq 0) { return $null }
    return (($lines | Select-Object -Last 12) -join ' | ').Substring(0, [math]::Min(1800, (($lines | Select-Object -Last 12) -join ' | ').Length))
}

function Write-JsonFile {
    param($Object, [string]$Path)
    $temporary = "$Path.tmp"
    $Object | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Set-ResultFailure {
    param($Result, [string]$Stage, [string]$Message, [string]$ErrorSummary)
    $Result['status'] = 'FAIL'
    $Result['failures'] = @($Result['failures']) + $Message
    $Result['failure_stage'] = $Stage
    $Result['error_summary'] = $ErrorSummary
}

function Wait-GitHubPagesBuild {
    param([string]$Commit, [int]$TimeoutSec = 600, [int]$PollSeconds = 15)
    $apiRoot = 'https://api.github.com/repos/zzyfsniper-code/sector-bias-dashboard'
    $headers = @{ Accept = 'application/vnd.github+json'; Authorization = "Bearer $env:GITHUB_TOKEN"; 'User-Agent' = 'three-strategy-pages-verifier' }
    $started = [DateTimeOffset]::Now
    $attempts = 0
    try {
        $settingsResponse = Invoke-WebRequest -Uri "$apiRoot/pages" -Headers $headers -UseBasicParsing -TimeoutSec 30
        $settings = $settingsResponse.Content | ConvertFrom-Json
        $buildType = [string]$settings.build_type
        if ($buildType -notin @('legacy', 'workflow')) { throw "Unsupported Pages build type: $buildType" }
        while ($true) {
            $attempts++
            if ($buildType -eq 'legacy') {
                $response = Invoke-WebRequest -Uri "$apiRoot/pages/builds?per_page=30" -Headers $headers -UseBasicParsing -TimeoutSec 30
                $allBuilds = $response.Content | ConvertFrom-Json
                $builds = @($allBuilds | Where-Object { $_.commit -eq $Commit })
                $completed = @($builds | Where-Object { $_.status -eq 'built' })
                $failed = @($builds | Select-Object -First 1 | Where-Object { $_.status -eq 'errored' })
            } else {
                $response = Invoke-WebRequest -Uri "$apiRoot/actions/runs?head_sha=$Commit&per_page=30" -Headers $headers -UseBasicParsing -TimeoutSec 30
                $runs = @(($response.Content | ConvertFrom-Json).workflow_runs | Where-Object { $_.name -eq 'Deploy to GitHub Pages' -and $_.head_sha -eq $Commit })
                $completed = @($runs | Where-Object { $_.status -eq 'completed' -and $_.conclusion -eq 'success' })
                $failed = @($runs | Select-Object -First 1 | Where-Object { $_.status -eq 'completed' -and $_.conclusion -in @('failure', 'cancelled', 'timed_out') })
            }
            if ($completed.Count -gt 0) {
                return [ordered]@{ status = 'PASS'; commit = $Commit; build_type = $buildType; attempts = $attempts; elapsed_seconds = [int]([DateTimeOffset]::Now - $started).TotalSeconds }
            }
            if ($failed.Count -gt 0) { throw "GitHub Pages build failed for commit $Commit" }
            if (([DateTimeOffset]::Now - $started).TotalSeconds -ge $TimeoutSec) {
                return [ordered]@{ status = 'TIMEOUT'; commit = $Commit; build_type = $buildType; attempts = $attempts; error_summary = "GitHub Pages build did not complete within $TimeoutSec seconds." }
            }
            Start-Sleep -Seconds $PollSeconds
        }
    } catch {
        return [ordered]@{ status = 'FAIL'; commit = $Commit; attempts = $attempts; error_summary = $_.Exception.Message }
    }
}

function Get-FailureStage {
    param([string]$ErrorSummary, [string[]]$Failures)
    if ($ErrorSummary -match '余额不足|insufficient balance') { return 'data_provider_insufficient_balance' }
    if ($ErrorSummary -match 'Wind crowding did not reach|881001\.WI') { return 'wind_crowding_freshness' }
    if ($ErrorSummary -match 'GitHub Pages did not expose') { return 'github_pages_verification' }
    if ($Failures -match 'publish\.') { return 'publish_validation' }
    if ($Failures -match 'data_quality|did not reach|coverage') { return 'data_freshness_validation' }
    return 'child_script_or_manifest_validation'
}

function Get-StrategyReport {
    param([string]$Key, $Manifest)
    if ($null -eq $Manifest) { return $null }
    switch ($Key) {
        'growth_value_five_dim' {
            return [ordered]@{
                composite_score = Get-NestedValue $Manifest @('validation', 'signal', 'compositeScore')
                dimensions = Get-NestedValue $Manifest @('validation', 'signal', 'dimensions')
                trading_plan = Get-NestedValue $Manifest @('validation', 'trading_plan')
            }
        }
        'csi500_flow_leverage' {
            return [ordered]@{
                trade = Get-NestedValue $Manifest @('trade')
                leverage = Get-NestedValue $Manifest @('leverage')
                indicators = Get-NestedValue $Manifest @('indicators')
            }
        }
        'all_weather_risk_parity' {
            return [ordered]@{
                trade = Get-NestedValue $Manifest @('trade')
                portfolio = Get-NestedValue $Manifest @('portfolio')
                performance = Get-NestedValue $Manifest @('performance')
            }
        }
    }
}

$strategies = @(
    [ordered]@{
        key = 'growth_value_five_dim'
        name = '五维成长价值轮动'
        runner = 'D:\agent工作目录\A股趋势看板\交易策略回测\strategies\growth_value_five_dim\run_daily_update.ps1'
        latest = 'D:\agent工作目录\A股趋势看板\交易策略回测\strategies\growth_value_five_dim\logs\daily\latest.json'
        url = 'https://zzyfsniper-code.github.io/sector-bias-dashboard/growth-value-five-dim/'
    },
    [ordered]@{
        key = 'csi500_flow_leverage'
        name = '中证500资金流向与底部杠杆'
        runner = 'D:\agent工作目录\A股趋势看板\交易策略回测\strategies\fund_flow_long_timing\run_daily_update.ps1'
        latest = 'D:\agent工作目录\A股趋势看板\交易策略回测\strategies\fund_flow_long_timing\logs\daily\latest.json'
        url = 'https://zzyfsniper-code.github.io/sector-bias-dashboard/csi500-flow-leverage/'
    },
    [ordered]@{
        key = 'all_weather_risk_parity'
        name = '多资产风险平价'
        runner = 'D:\agent工作目录\数据看板工作文件夹\strategies\all_weather_risk_parity\run_daily_update.ps1'
        latest = 'D:\agent工作目录\数据看板工作文件夹\strategies\all_weather_risk_parity\logs\daily\latest.json'
        url = 'https://zzyfsniper-code.github.io/sector-bias-dashboard/all-weather-risk-parity/'
    }
)

$startedAt = [DateTimeOffset]::Now
$batchId = 'three_strategy_live_{0}_{1}' -f $startedAt.ToString('yyyyMMdd'), $startedAt.ToString('HHmmss')
$results = [System.Collections.Generic.List[object]]::new()
$publisher = Join-Path $strategyDir 'publish_github_pages.py'
$centerUrl = 'https://zzyfsniper-code.github.io/sector-bias-dashboard/strategies/'
$batchPublish = [ordered]@{ status = if ($ValidateOnly) { 'NOT_RUN' } else { 'PENDING' }; commit = $null; online_status = 'PENDING' }

foreach ($strategy in $strategies) {
    $before = Read-JsonFile $strategy.latest
    $oldRunId = [string](Get-NestedValue $before @('run_id'))
    $stdoutPath = Join-Path $logDir "$batchId.$($strategy.key).stdout.log"
    $stderrPath = Join-Path $logDir "$batchId.$($strategy.key).stderr.log"
    $exitCode = 0

    if (-not $ValidateOnly) {
        $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$($strategy.runner)`" -SkipPublish"
        if (-not [string]::IsNullOrWhiteSpace($AsOf)) { $arguments += " -AsOf $AsOf" }
        try {
            $process = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
            $exitCode = [int]$process.ExitCode
        } catch {
            $exitCode = -1
            Set-Content -LiteralPath $stderrPath -Value $_.Exception.Message -Encoding UTF8
        }
    }

    $after = Read-JsonFile $strategy.latest
    $failures = [System.Collections.Generic.List[string]]::new()
    foreach ($failure in @(Test-CommonManifest $after $exitCode $oldRunId (-not $ValidateOnly) $ValidateOnly)) { $failures.Add([string]$failure) | Out-Null }
    switch ($strategy.key) {
        'growth_value_five_dim' { foreach ($failure in @(Test-GrowthManifest $after)) { $failures.Add([string]$failure) | Out-Null } }
        'csi500_flow_leverage' { foreach ($failure in @(Test-Csi500Manifest $after)) { $failures.Add([string]$failure) | Out-Null } }
        'all_weather_risk_parity' { foreach ($failure in @(Test-RiskParityManifest $after (-not $ValidateOnly))) { $failures.Add([string]$failure) | Out-Null } }
    }

    $errorSummary = if ($ValidateOnly) { $null } else { Get-ErrorSummary $stdoutPath $stderrPath }
    $resultStatus = if ($failures.Count -eq 0) { 'PASS' } else { 'FAIL' }
    $results.Add([ordered]@{
        strategy = $strategy.key
        name = $strategy.name
        status = $resultStatus
        exit_code = $exitCode
        old_run_id = $oldRunId
        run_id = [string](Get-NestedValue $after @('run_id'))
        target_trade_date = Get-NestedValue $after @('target_trade_date')
        failures = $failures.ToArray()
        failure_stage = if ($resultStatus -eq 'FAIL') { Get-FailureStage $errorSummary $failures.ToArray() } else { $null }
        error_summary = if ($resultStatus -eq 'FAIL') { $errorSummary } else { $null }
        stdout_log = if ($ValidateOnly) { $null } else { $stdoutPath }
        stderr_log = if ($ValidateOnly) { $null } else { $stderrPath }
        publish = Get-NestedValue $after @('publish')
        page_url = $strategy.url
        report = Get-StrategyReport $strategy.key $after
    }) | Out-Null
}

if (-not $ValidateOnly) {
    $publishable = @($results | Where-Object { $_.status -eq 'PASS' })
    if ($publishable.Count -gt 0) {
        $publishStdout = Join-Path $logDir "$batchId.publish.stdout.log"
        $publishStderr = Join-Path $logDir "$batchId.publish.stderr.log"
        $publishExitCode = -1
        try {
            $githubToken = [Environment]::GetEnvironmentVariable('GITHUB_TOKEN', 'Process')
            if ([string]::IsNullOrWhiteSpace($githubToken)) { $githubToken = [Environment]::GetEnvironmentVariable('GITHUB_TOKEN', 'User') }
            if ([string]::IsNullOrWhiteSpace($githubToken)) { throw 'GITHUB_TOKEN is not configured.' }
            $env:GITHUB_TOKEN = $githubToken
            $publishArguments = "-3 `"$publisher`" --message `"data: update three strategies $batchId`""
            $publishProcess = Start-Process -FilePath 'py' -ArgumentList $publishArguments -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput $publishStdout -RedirectStandardError $publishStderr
            $publishExitCode = [int]$publishProcess.ExitCode
            if ($publishExitCode -ne 0) { throw "Combined GitHub publish failed with exit code $publishExitCode." }
            $publishLines = @(Get-Content -LiteralPath $publishStdout -Encoding UTF8 | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
            if ($publishLines.Count -eq 0) { throw 'Combined GitHub publisher returned no result.' }
            $publishResult = $publishLines[-1] | ConvertFrom-Json
            if ($publishResult.status -ne 'PASS' -or [string]::IsNullOrWhiteSpace([string]$publishResult.commit)) {
                throw 'Combined GitHub publisher did not return a valid commit.'
            }
            $batchPublish['status'] = 'PUSHED_SCOPED'
            $batchPublish['commit'] = [string]$publishResult.commit
            $batchPublish['files'] = [int]$publishResult.files

            Start-Sleep -Seconds 60
            Start-Sleep -Seconds 60
            $buildResult = Wait-GitHubPagesBuild ([string]$publishResult.commit)
            $batchPublish['build'] = $buildResult
            if ($buildResult.status -ne 'PASS') { throw $buildResult.error_summary }
            # Allow the completed build to reach the Pages CDN before the single final check.
            Start-Sleep -Seconds 30
            $verifyInput = Join-Path $logDir "$batchId.verify-input.json"
            $verifyStdout = Join-Path $logDir "$batchId.verify.stdout.log"
            $verifyStderr = Join-Path $logDir "$batchId.verify.stderr.log"
            Write-JsonFile ([ordered]@{
                run_id = $batchId
                strategy_center = $centerUrl
                strategies = @($publishable | ForEach-Object { [ordered]@{ strategy = $_['strategy']; run_id = $_['run_id']; page_url = $_['page_url'] } })
            }) $verifyInput
            $verifier = Join-Path $strategyDir 'verify_online.py'
            $verifyProcess = Start-Process -FilePath 'py' -ArgumentList "-3 `"$verifier`" --batch-file `"$verifyInput`"" -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput $verifyStdout -RedirectStandardError $verifyStderr
            $verifyLines = @(Get-Content -LiteralPath $verifyStdout -Encoding UTF8 | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
            if ([int]$verifyProcess.ExitCode -notin @(0, 1) -or $verifyLines.Count -eq 0) { throw 'The online verifier did not return a valid result. See verify stdout/stderr logs.' }
            $verification = $verifyLines[-1] | ConvertFrom-Json
            $batchPublish['verification'] = $verification
            $batchPublish['verification_stdout_log'] = $verifyStdout
            $batchPublish['verification_stderr_log'] = $verifyStderr
            $centerOnline = $verification.center.status -eq 'PASS'
            if (-not $centerOnline) {
                $batchPublish['failure_stage'] = 'strategy_center_online_verification'
                $batchPublish['error_summary'] = 'The strategy center check failed: ' + $verification.center.error_summary
            }

            $onlinePassed = 0
            foreach ($result in $publishable) {
                $runId = [string]$result['run_id']
                $pageCheck = @($verification.strategies | Where-Object { $_.strategy -eq $result['strategy'] })
                if ($pageCheck.Count -ne 1) { throw "Missing or duplicated verification result for $($result['strategy'])." }
                $pageCheck = $pageCheck[0]
                $onlineVerified = $pageCheck.status -eq 'PASS' -and $pageCheck.verified_run_id -eq $runId
                if ($onlineVerified) { $onlinePassed++ }
                if (-not $onlineVerified) {
                    $verificationError = "$($pageCheck.error_type): $($pageCheck.error_summary)"
                    Set-ResultFailure $result 'batch_online_verification' "online verification failed for $runId after the completed Pages build" $verificationError
                }
                try {
                    $strategy = $strategies | Where-Object { $_.key -eq $result['strategy'] } | Select-Object -First 1
                    $manifest = Read-JsonFile $strategy.latest
                    $manifest.publish | Add-Member -NotePropertyName git_status -NotePropertyValue 'PUSHED_SCOPED' -Force
                    $manifest.publish | Add-Member -NotePropertyName online_status -NotePropertyValue $(if ($onlineVerified) { 'PASS' } else { 'FAIL' }) -Force
                    $manifest.publish | Add-Member -NotePropertyName url -NotePropertyValue $result['page_url'] -Force
                    $manifest.publish | Add-Member -NotePropertyName center_url -NotePropertyValue $centerUrl -Force
                    $manifest.publish | Add-Member -NotePropertyName commit -NotePropertyValue ([string]$publishResult.commit) -Force
                    $manifest.publish | Add-Member -NotePropertyName verified_run_id -NotePropertyValue $(if ($onlineVerified) { $runId } else { $null }) -Force
                    $result['publish'] = $manifest.publish
                    Write-JsonFile $manifest $strategy.latest
                } catch {
                    Set-ResultFailure $result 'result_persistence' 'failed to save the child publication result' $_.Exception.Message
                }
            }
            $batchPublish['online_status'] = if ($centerOnline -and $onlinePassed -eq $publishable.Count) { 'PASS' } else { 'FAIL' }
        } catch {
            if ($null -eq $batchPublish['commit']) { $batchPublish['status'] = 'FAIL' }
            $batchPublish['online_status'] = 'FAIL'
            $batchPublish['error_summary'] = $_.Exception.Message
            foreach ($result in $publishable) {
                $stage = if ($null -eq $batchPublish['commit']) { 'batch_github_publish' } elseif ($batchPublish.Contains('build') -and $batchPublish['build']['status'] -ne 'PASS') { 'batch_pages_build' } else { 'batch_finalization' }
                Set-ResultFailure $result $stage 'combined publication flow did not complete' $_.Exception.Message
            }
        }
        $batchPublish['stdout_log'] = $publishStdout
        $batchPublish['stderr_log'] = $publishStderr
        $batchPublish['exit_code'] = $publishExitCode
    } else {
        $batchPublish['status'] = 'SKIPPED'
        $batchPublish['online_status'] = 'SKIPPED'
        $batchPublish['reason'] = 'No child strategy produced a valid new batch.'
    }
}

$passCount = @($results | Where-Object { $_.status -eq 'PASS' }).Count
$overallStatus = if ($passCount -eq $strategies.Count) { 'PASS' } elseif ($passCount -eq 0) { 'FAIL' } else { 'PARTIAL' }
if (-not $ValidateOnly -and $overallStatus -eq 'PASS' -and $batchPublish['online_status'] -ne 'PASS') { $overallStatus = 'PARTIAL' }
$batch = [ordered]@{
    schema_version = '1.0'
    run_id = $batchId
    status = $overallStatus
    mode = if ($ValidateOnly) { 'VALIDATE_ONLY' } else { 'RUN_ONCE_SERIAL' }
    requested_as_of = if ([string]::IsNullOrWhiteSpace($AsOf)) { $null } else { $AsOf }
    started_at = $startedAt.ToString('o')
    finished_at = [DateTimeOffset]::Now.ToString('o')
    execution_contract = 'The orchestrator runs each child script once in fixed serial order, creates one combined GitHub commit, waits at least two minutes plus the matching Pages build (up to ten additional minutes), allows thirty seconds for CDN propagation, and verifies all successful strategy pages once.'
    counts = [ordered]@{ total = $strategies.Count; passed = $passCount; failed = $strategies.Count - $passCount }
    publish = $batchPublish
    strategies = $results.ToArray()
    strategy_center = 'https://zzyfsniper-code.github.io/sector-bias-dashboard/strategies/'
}

$json = $batch | ConvertTo-Json -Depth 100
$runPath = Join-Path $logDir "$batchId.json"
$latestPath = Join-Path $logDir 'latest.json'
$tempPath = Join-Path $logDir 'latest.json.tmp'
Set-Content -LiteralPath $runPath -Value $json -Encoding UTF8
Set-Content -LiteralPath $tempPath -Value $json -Encoding UTF8
Move-Item -LiteralPath $tempPath -Destination $latestPath -Force
Write-Output ($batch | ConvertTo-Json -Depth 100 -Compress)

if ($overallStatus -eq 'PASS') { exit 0 }
if ($overallStatus -eq 'PARTIAL') { exit 2 }
exit 1
