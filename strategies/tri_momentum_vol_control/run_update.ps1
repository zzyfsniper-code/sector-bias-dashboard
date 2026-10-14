[CmdletBinding()]
param([string]$PythonPath='C:\Users\86136\AppData\Local\Programs\Python\Python312\python.exe')
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$logDir=Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logFile=Join-Path $logDir ('nightly_'+(Get-Date -Format 'yyyyMMdd_HHmmss')+'.log')
$mutex=[Threading.Mutex]::new($false,'Local\TriMomentumVolControlNightly')
$locked=$false; $exitCode=1
try {
 $locked=$mutex.WaitOne(0)
 if (-not $locked) { throw 'A three-asset update is already running' }
 if ((Get-Date).DayOfWeek -in @([DayOfWeek]::Saturday,[DayOfWeek]::Sunday)) { $exitCode=0; 'SKIP weekend' | Out-File -LiteralPath $logFile -Encoding utf8 }
 else {
  $arguments='-u "{0}" --publish' -f (Join-Path $PSScriptRoot 'update.py')
  $process=Start-Process -FilePath $PythonPath -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $logFile -RedirectStandardError ($logFile+'.stderr.log')
  $exitCode=$process.ExitCode
 }
} catch { $_.Exception.Message | Out-File -LiteralPath $logFile -Append -Encoding utf8 }
finally { if ($locked) { $mutex.ReleaseMutex() }; $mutex.Dispose() }
exit $exitCode
