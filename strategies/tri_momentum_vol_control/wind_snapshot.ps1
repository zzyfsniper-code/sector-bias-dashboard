[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$OutputFile, [int]$TimeoutSeconds=45)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class TriWindNative {
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
}
"@
$codes = @('159696.SZ','510300.SH','518880.SH')
$fields = @('RT_LAST','RT_PRE_CLOSE','RT_DATE','RT_TIME','RT_BID1','RT_ASK1','RT_VOL','RT_AMT')
$existing = @(Get-Process EXCEL -ErrorAction SilentlyContinue | ForEach-Object Id)
$excel=$null; $book=$null; $sheet=$null; $calSheet=$null; $addin=$null
$excelPid=[uint32]0; $dedicated=$false; $failure=$null; $quotes=@(); $calendar=@()
$started=Get-Date
$calStart=$started.AddDays(-45).ToString('yyyy-MM-dd')
$calEnd=$started.AddDays(120).ToString('yyyy-MM-dd')
function Read-DateValue($value) {
 $number=0.0
 if ([double]::TryParse([string]$value,[ref]$number)) {
  if ($number -gt 30000 -and $number -lt 80000) { return [datetime]::FromOADate($number).ToString('yyyy-MM-dd') }
  if ([string]$value -match '^\d{8}$') { return [datetime]::ParseExact([string]$value,'yyyyMMdd',$null).ToString('yyyy-MM-dd') }
 }
 $parsed=[datetime]::MinValue
 if ([datetime]::TryParse([string]$value,[ref]$parsed)) { return $parsed.ToString('yyyy-MM-dd') }
 return $null
}
function Read-TimeValue($value) {
 $number=0.0
 if ([double]::TryParse([string]$value,[ref]$number)) {
  if ($number -gt 0 -and $number -lt 1) { return [datetime]::FromOADate($number).ToString('HH:mm:ss') }
  $digits=([math]::Truncate($number)).ToString().PadLeft(6,'0')
  if ($digits -match '^([0-2]\d)([0-5]\d)([0-5]\d)$') { return '{0}:{1}:{2}' -f $Matches[1],$Matches[2],$Matches[3] }
 }
 $parsed=[datetime]::MinValue
 if ([datetime]::TryParse([string]$value,[ref]$parsed)) { return $parsed.ToString('HH:mm:ss') }
 return $null
}
function Read-Number($value) {
 $number=0.0
 if ([double]::TryParse([string]$value,[Globalization.NumberStyles]::Any,[Globalization.CultureInfo]::InvariantCulture,[ref]$number)) { return $number }
 return $null
}
try {
 $excel=New-Object -ComObject Excel.Application
 [TriWindNative]::GetWindowThreadProcessId([IntPtr]$excel.Hwnd,[ref]$excelPid) | Out-Null
 $dedicated=$existing -notcontains [int]$excelPid
 if (-not $dedicated) { throw 'Refusing to modify an existing Excel process' }
 $excel.Visible=$false; $excel.DisplayAlerts=$false
 $addin=$excel.COMAddIns.Item('WDF.Addin')
 if (-not $addin.Connect) { throw 'WDF.Addin is not connected' }
 $book=$excel.Workbooks.Add(); $sheet=$book.Worksheets.Item(1)
 $calSheet=$book.Worksheets.Add(); $calSheet.Name='calendar'
 $calSheet.Range('A1').Formula=('=TDAYS("{0}","{1}","TradingCalendar=SSE")' -f $calStart,$calEnd)
 for ($r=0; $r -lt $codes.Count; $r++) {
  for ($c=0; $c -lt $fields.Count; $c++) { $sheet.Cells.Item($r+1,$c+1).Formula=('=WSS("{0}","{1}")' -f $codes[$r],$fields[$c]) }
 }
 $excel.CalculateFull(); $deadline=(Get-Date).AddSeconds($TimeoutSeconds)
 do {
  Start-Sleep -Milliseconds 500
  $quotes=@()
  for ($r=0; $r -lt $codes.Count; $r++) {
   $values=@{}
   for ($c=0; $c -lt $fields.Count; $c++) {
    $cell=$sheet.Cells.Item($r+1,$c+1)
    if ([string]$cell.Text -match '^#(NAME\?|VALUE!|REF!|N/A|NUM!|NULL!|DIV/0!)$') { throw "Wind WSS formula error: $($cell.Text)" }
    $values[$fields[$c]]=$cell.Value2
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($cell)
   }
   $quotes+= [ordered]@{code=$codes[$r];last=(Read-Number $values.RT_LAST);pre_close=(Read-Number $values.RT_PRE_CLOSE);quote_date=(Read-DateValue $values.RT_DATE);quote_time=(Read-TimeValue $values.RT_TIME);bid1=(Read-Number $values.RT_BID1);ask1=(Read-Number $values.RT_ASK1);volume=(Read-Number $values.RT_VOL);amount=(Read-Number $values.RT_AMT)}
  }
  $calendar=@()
  $calValues=$calSheet.UsedRange.Value2
  foreach ($value in $calValues) {
   $day=Read-DateValue $value
   if ($day -and $day -ge $calStart -and $day -le $calEnd) { $calendar+=$day }
  }
  $calendar=@($calendar | Sort-Object -Unique)
  $ready=(@($quotes | Where-Object { $_.last -gt 0 -and $_.pre_close -gt 0 -and $_.quote_date -and $_.quote_time }).Count -eq 3 -and $calendar.Count -gt 50)
 } while (-not $ready -and (Get-Date) -lt $deadline)
 if (-not $ready) { throw 'Wind Excel snapshot/calendar timeout' }
} catch { $failure=$_.Exception.Message }
finally {
 if ($book -and $dedicated) { try { $book.Close($false) } catch {} }
 if ($excel -and $dedicated) { try { $excel.Quit() } catch {} }
 foreach ($obj in @($calSheet,$sheet,$book,$addin,$excel)) { if ($null -ne $obj) { try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($obj) } catch {} } }
 [gc]::Collect(); [gc]::WaitForPendingFinalizers()
 if ($dedicated -and $excelPid -gt 0) {
  $deadline=(Get-Date).AddSeconds(5)
  while ((Get-Date) -lt $deadline -and (Get-Process -Id $excelPid -ErrorAction SilentlyContinue)) { Start-Sleep -Milliseconds 250 }
  if (Get-Process -Id $excelPid -ErrorAction SilentlyContinue) { Stop-Process -Id $excelPid -Force }
 }
}
$result=[ordered]@{status=$(if ($failure) {'FAIL'} else {'PASS'});source='Wind Excel WDF.Addin WSS + TDAYS';observed_at=(Get-Date).ToString('o');error=$failure;calendar_start=$calStart;calendar_end=$calEnd;calendar=$calendar;quotes=$quotes;dedicated_excel_process=$dedicated;current_user_workbook_touched=$false;elapsed_seconds=[math]::Round(((Get-Date)-$started).TotalSeconds,2)}
$absolute=[IO.Path]::GetFullPath($OutputFile)
[IO.Directory]::CreateDirectory((Split-Path -Parent $absolute)) | Out-Null
[IO.File]::WriteAllText($absolute,($result | ConvertTo-Json -Depth 12),[Text.UTF8Encoding]::new($false))
if ($failure) { throw $failure }
Write-Output ('PASS snapshot={0} calendar_days={1}' -f $absolute,$calendar.Count)
