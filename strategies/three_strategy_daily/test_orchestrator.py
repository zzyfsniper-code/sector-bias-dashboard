"""Run the actual PowerShell controller with isolated files and mocked external work."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
SOURCES = [
    Path(r"D:\agent工作目录\A股趋势看板\交易策略回测\strategies\growth_value_five_dim\logs\daily\latest.json"),
    Path(r"D:\agent工作目录\A股趋势看板\交易策略回测\strategies\fund_flow_long_timing\logs\daily\latest.json"),
    Path(r"D:\agent工作目录\数据看板工作文件夹\strategies\all_weather_risk_parity\logs\daily\latest.json"),
]
HARNESS = r"""
$ErrorActionPreference = 'Stop'
$env:GITHUB_TOKEN = 'fixture-only'
$script:scenario = '__SCENARIO__'
$script:fixtureRoot = $PSScriptRoot
function Start-Process {
    param($FilePath, $ArgumentList, [switch]$Wait, [switch]$PassThru,
          $WindowStyle, $RedirectStandardOutput, $RedirectStandardError)
    Set-Content $RedirectStandardError '' -Encoding UTF8
    if ($FilePath -eq 'py') {
        Add-Content "$script:fixtureRoot/events.txt" 'publish'
        Set-Content $RedirectStandardOutput '{"status":"PASS","commit":"fixture-sha","files":19}' -Encoding UTF8
        return [pscustomobject]@{ExitCode=$(if($script:scenario -eq 'publish_fail'){1}else{0})}
    }
    if ($ArgumentList -notmatch '-SkipPublish') { throw 'Child publication was not disabled' }
    $index = if($ArgumentList -match 'growth_value_five_dim'){0}elseif($ArgumentList -match 'fund_flow_long_timing'){1}else{2}
    Add-Content "$script:fixtureRoot/events.txt" "child-$index"
    $file = "$script:fixtureRoot/child-$index.json"
    $manifest = Get-Content $file -Raw -Encoding UTF8 | ConvertFrom-Json
    $manifest.run_id += '_fixture'
    $manifest | ConvertTo-Json -Depth 100 | Set-Content $file -Encoding UTF8
    Set-Content $RedirectStandardOutput '{}' -Encoding UTF8
    return [pscustomobject]@{ExitCode=0}
}
function Start-Sleep {
    param($Seconds)
    Add-Content "$script:fixtureRoot/events.txt" "sleep-$Seconds"
}
function Invoke-WebRequest {
    param($Uri, [switch]$UseBasicParsing, $TimeoutSec)
    Add-Content "$script:fixtureRoot/events.txt" 'online'
    $run = [uri]::UnescapeDataString(([string]$Uri -split 'run=')[1])
    if($script:scenario -eq 'stale' -and $Uri -match 'csi500-flow-leverage'){$run='old-run'}
    return [pscustomobject]@{StatusCode=200;Content=$run}
}
. "$PSScriptRoot/controller.ps1"
exit $LASTEXITCODE
"""


class ControllerTest(unittest.TestCase):
    def exercise(self, scenario):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            controller = (ROOT / "run_daily_update.ps1").read_text(encoding="utf-8-sig")
            for index, source in enumerate(SOURCES):
                manifest = json.loads(source.read_text(encoding="utf-8-sig"))
                manifest["publish"] = {"git_status": "PENDING"}
                if index == 0:
                    manifest["publish"]["copy_status"] = "PASS"
                fixture = directory / f"child-{index}.json"
                fixture.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
                controller = controller.replace(str(source), str(fixture))
            if scenario == "save_fail":
                controller = controller.replace(
                    '$temporary = "$Path.tmp"',
                    'if ($Path -like "*child-1.json") { throw "fixture disk write failure" }\n    $temporary = "$Path.tmp"')
            (directory / "controller.ps1").write_text(controller, encoding="utf-8-sig")
            harness = directory / "harness.ps1"
            harness.write_text(HARNESS.replace("__SCENARIO__", scenario), encoding="utf-8-sig")
            process = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                capture_output=True, timeout=30)
            latest = directory / "logs/daily/latest.json"
            self.assertTrue(latest.exists(), process.stderr.decode(errors="replace"))
            result = json.loads(latest.read_text(encoding="utf-8-sig"))
            events = (directory / "events.txt").read_text().splitlines()
            self.assertEqual(events[:4], ["child-0", "child-1", "child-2", "publish"])
            self.assertEqual(events.count("publish"), 1)
            if scenario != "publish_fail":
                self.assertEqual(events[4:6], ["sleep-60", "sleep-60"])
                self.assertEqual(events.count("online"), 4)
            children = [json.loads((directory / f"child-{i}.json").read_text(encoding="utf-8-sig")) for i in range(3)]
            return process.returncode, result, children

    def test_missing_online_status_completes_all_three(self):
        code, result, children = self.exercise("pass")
        self.assertEqual((code, result["status"], result["counts"]["passed"]), (0, "PASS", 3))
        for child in children:
            self.assertEqual(child["publish"]["online_status"], "PASS")
            self.assertEqual(child["publish"]["verified_run_id"], child["run_id"])
            self.assertEqual(child["publish"]["commit"], "fixture-sha")

    def test_write_failure_does_not_mark_other_strategies_failed(self):
        code, result, children = self.exercise("save_fail")
        self.assertEqual((code, result["counts"]["passed"]), (2, 2))
        self.assertEqual(result["publish"]["status"], "PUSHED_SCOPED")
        self.assertEqual(result["strategies"][1]["failure_stage"], "result_persistence")
        self.assertEqual(result["publish"]["online_status"], "PASS")
        self.assertEqual(children[2]["publish"]["online_status"], "PASS")

    def test_stale_page_preserves_successful_commit(self):
        code, result, children = self.exercise("stale")
        self.assertEqual((code, result["counts"]["passed"]), (2, 2))
        self.assertEqual(children[1]["publish"]["git_status"], "PUSHED_SCOPED")
        self.assertIsNone(children[1]["publish"]["verified_run_id"])
        self.assertEqual(result["strategies"][1]["failure_stage"], "batch_online_verification")

    def test_publish_failure_is_identified(self):
        code, result, _ = self.exercise("publish_fail")
        self.assertEqual((code, result["status"]), (1, "FAIL"))
        self.assertEqual(result["strategies"][0]["failure_stage"], "batch_github_publish")


if __name__ == "__main__":
    unittest.main()
