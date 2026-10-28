from pathlib import Path
import shutil
import subprocess

import pytest

# AgentChat/direct_codex 2026-07-13T00:16:00-04:00
# AgentChat/coding_agent 2026-07-13T00:55:00-04:00


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _powershell_executable() -> str:
    executable = shutil.which("powershell.exe") or shutil.which("pwsh")
    if not executable:
        pytest.skip("PowerShell is unavailable on this test host")
    return executable


def _script(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def _assert_powershell_parses(name: str) -> None:
    path = SCRIPTS / name
    quoted_path = str(path).replace("'", "''")
    command = (
        "$tokens = $null; $errors = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{quoted_path}', [ref]$tokens, [ref]$errors); "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    completed = subprocess.run(
        [_powershell_executable(), "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def _run_start_script_with_mock_existing(name: str, *, supervised: bool) -> subprocess.CompletedProcess[str]:
    path = SCRIPTS / name
    quoted_path = str(path).replace("'", "''")
    supervised_arg = " -Supervised -MaxRestarts 2 -RestartDelaySeconds 0" if supervised else ""
    command = f"""
$global:fakeProcess = [pscustomobject]@{{
  Id = 4242
  ProcessId = 4242
  Name = 'python.exe'
  CommandLine = 'py -3 -m codex_slack_bridge.app'
  ExitCode = 23
}}
$global:fakeProcess | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {{ Write-Output '__WAITED__' }}
$global:fakeProcess | Add-Member -MemberType ScriptMethod -Name Refresh -Value {{ Write-Output '__REFRESHED__' }}
function global:Get-CimInstance {{ $global:fakeProcess }}
function global:Get-Process {{ $global:fakeProcess }}
function global:Invoke-RestMethod {{
  [pscustomobject]@{{ ok = $true; service = 'nova-ops-command-center'; processId = 4242 }}
}}
& '{quoted_path}'{supervised_arg}
"""
    return subprocess.run(
        [_powershell_executable(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )


def test_command_center_start_is_health_checked_and_logged() -> None:
    script = _script("start-command-center-server.ps1")

    assert script.index("Invoke-RestMethod -Uri $HealthUrl") < script.index("Start-Process")
    assert 'Join-Path $Root "logs\\command_center"' in script
    assert '"gateway-$Port.out.log"' in script
    assert '"gateway-$Port.err.log"' in script
    assert "-RedirectStandardOutput $StdoutLog" in script
    assert "-RedirectStandardError $StderrLog" in script
    assert "gateway is already healthy" in script


def test_command_center_start_reclaims_only_confirmed_stale_gateway_processes() -> None:
    script = _script("start-command-center-server.ps1")
    detector = script.index("function Get-StaleCommandCenterProcesses")
    exact_module = script.index("codex_slack_bridge\\.command_center_server", detector)
    exact_port = script.index("--port\\s+", detector)
    cleanup = script.index("function Remove-StaleCommandCenterProcesses")
    repeated_health = script.index("for ($Attempt = 0; $Attempt -lt 2", cleanup)
    stop = script.index("Stop-Process -Id $ProcessIds", repeated_health)
    call = script.index("Remove-StaleCommandCenterProcesses", stop)
    launch = script.index("Start-Process", call)

    assert detector < exact_module < cleanup < repeated_health < stop < call < launch
    assert detector < exact_port < cleanup
    assert '$_ .Name' not in script
    assert '$_.Name -in @("py.exe", "python.exe", "python3.exe")' in script


def test_startup_installers_use_restart_on_failure_scheduled_tasks() -> None:
    cases = {
        "install-startup-task.ps1": "CodexSlackBridge",
        "install-command-center-startup-task.ps1": "CodexCommandCenter",
    }

    for filename, value_name in cases.items():
        script = _script(filename)
        assert "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" in script
        assert f'[string]$RegistryValueName = "{value_name}"' in script
        assert "Register-ScheduledTask" in script
        assert "New-ScheduledTaskSettingsSet" in script
        assert "-RestartCount 999" in script
        assert "-RestartInterval" in script
        assert "-ExecutionTimeLimit (New-TimeSpan -Seconds 0)" in script
        assert 'Remove-ItemProperty -Path $runKey -Name $RegistryValueName' in script
        assert '$supervisedArguments = "-NoProfile' in script
        assert '-Supervised"' in script
        assert "Legacy HKCU Run and Startup folder entries are absent." in script


def test_supervised_start_scripts_adopt_existing_processes_instead_of_exiting() -> None:
    cases = {
        "start.ps1": "Supervising existing Codex Slack Bridge",
        "start-command-center-server.ps1": "Supervising existing Nova Ops Command Center gateway",
    }

    for filename, adoption_message in cases.items():
        script = _script(filename)
        adoption = script.index(adoption_message)
        wait = script.index(".WaitForExit()", adoption)
        restart_policy = script.index("supervised launcher will restart it", wait)
        no_duplicate_exit = script.index("exit 0")

        assert "if (-not $Supervised)" in script[:adoption]
        assert no_duplicate_exit < adoption < wait < restart_policy


def test_supervised_start_scripts_wait_on_mock_existing_process_and_return_failure() -> None:
    for filename in ("start.ps1", "start-command-center-server.ps1"):
        completed = _run_start_script_with_mock_existing(filename, supervised=True)

        # The bounded test seam exits non-zero after proving two supervisor cycles.
        assert completed.returncode != 0, completed.stderr or completed.stdout
        assert completed.stdout.count("__WAITED__") == 2
        assert completed.stdout.count("__REFRESHED__") == 2
        assert "exited with code 23" in completed.stdout
        assert "supervised launcher will restart it" in completed.stdout


def test_non_supervised_start_scripts_keep_no_duplicate_early_exit() -> None:
    for filename in ("start.ps1", "start-command-center-server.ps1"):
        completed = _run_start_script_with_mock_existing(filename, supervised=False)

        assert completed.returncode == 0, completed.stderr or completed.stdout
        assert "__WAITED__" not in completed.stdout
        assert "already" in completed.stdout.lower()


def test_installers_preserve_supervised_fallback_until_task_readback_is_verified() -> None:
    for filename in ("install-startup-task.ps1", "install-command-center-startup-task.ps1"):
        script = _script(filename)
        register = script.index("Register-ScheduledTask")
        readback = script.index("Test-SupervisedScheduledTask $installed", register)
        start_now = script.index("if ($scheduledVerified -and $StartNow)", readback)
        running_readback = script.index("did not enter Running state", start_now)
        verified_branch = script.index("if ($scheduledVerified)", running_readback)
        remove_fallback = script.index("Remove-Item -LiteralPath $legacyLauncher", verified_branch)
        branch_return = script.index("return", remove_fallback)
        fallback_body = script.index("$launcherBody =", branch_return)
        fallback_verify = script.index("Supervised Startup folder fallback verification failed", fallback_body)

        assert register < readback < start_now < running_readback < verified_branch < remove_fallback
        assert remove_fallback < branch_return < fallback_body < fallback_verify
        assert "powershell.exe $supervisedArguments" in script[fallback_body:]
        assert ":supervise" in script[fallback_body:]
        assert "timeout /t 5 /nobreak >nul" in script[fallback_body:]
        assert "goto supervise" in script[fallback_body:]
        assert "Move-Item -LiteralPath $launcherTemp -Destination $legacyLauncher -Force" in script[fallback_body:]
        assert "-FilePath $env:ComSpec" in script[fallback_body:]


def test_start_scripts_keep_supervised_launcher_alive() -> None:
    for filename in ("start.ps1", "start-command-center-server.ps1"):
        script = _script(filename)
        assert "[switch]$Supervised" in script
        assert "[int]$MaxRestarts = 0" in script
        assert "while ($true)" in script
        assert "if (-not $Supervised)" in script
        assert ".WaitForExit()" in script
        assert "supervised launcher will restart it" in script
        assert "Start-Sleep -Seconds ([Math]::Max(0, $RestartDelaySeconds))" in script


def test_startup_uninstallers_remove_current_and_legacy_entries() -> None:
    for filename in (
        "uninstall-startup-task.ps1",
        "uninstall-command-center-startup-task.ps1",
    ):
        script = _script(filename)
        assert "Remove-ItemProperty" in script
        assert "Unregister-ScheduledTask" in script
        assert "Remove-Item -LiteralPath $launcher" in script


def test_all_startup_powershell_scripts_parse() -> None:
    for filename in (
        "start.ps1",
        "start-command-center-server.ps1",
        "install-startup-task.ps1",
        "install-command-center-startup-task.ps1",
        "uninstall-startup-task.ps1",
        "uninstall-command-center-startup-task.ps1",
    ):
        _assert_powershell_parses(filename)
