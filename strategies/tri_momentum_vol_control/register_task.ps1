[CmdletBinding()]
param([switch]$ValidateOnly)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$name='TriMomentumVolControl-Nightly-1810'
$script=Join-Path $PSScriptRoot 'run_update.ps1'
$python=(Get-Command python.exe -ErrorAction Stop).Source
$arguments='-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -PythonPath "{1}"' -f $script,$python
if (-not $ValidateOnly) {
 if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { throw 'Task already exists; refusing to overwrite it' }
 $action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent)
 $trigger=New-ScheduledTaskTrigger -Daily -At '18:10'
 $principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
 $settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 25) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
 Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Three-asset momentum: 18:10 Wind Excel update and GitHub publish. No Codex dependency; no orders.' | Out-Null
}
$task=Get-ScheduledTask -TaskName $name -ErrorAction Stop
$info=Get-ScheduledTaskInfo -TaskName $name
if ($task.Actions.Arguments -ne $arguments) { throw 'Scheduled task action mismatch' }
[pscustomobject]@{status='PASS';task_name=$task.TaskName;state=[string]$task.State;next_run=$info.NextRunTime.ToString('o');logon_type=[string]$task.Principal.LogonType;codex_dependency=$false;auto_order=$false} | ConvertTo-Json
