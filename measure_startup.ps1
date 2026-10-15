param([switch]$Windowed)
# Optional direct-launch measurement. Does not change Windows saver settings.
$ErrorActionPreference = 'Stop'
$rnsLogDirectory = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Path $rnsLogDirectory -Force | Out-Null
$rnsLogFile = Join-Path $rnsLogDirectory ('startup_launch_' + (Get-Date -Format 'yyyyMMdd_HHmmss_ffff') + '.jsonl')
function Write-RnsLaunchEvent($rnsEvent) {
    try {
        $rnsEvent.time = [DateTimeOffset]::Now.ToString('o')
        $rnsEvent.stopwatch_ticks = [Diagnostics.Stopwatch]::GetTimestamp()
        $rnsEvent.stopwatch_frequency = [Diagnostics.Stopwatch]::Frequency
        $rnsEvent | ConvertTo-Json -Compress | Add-Content -LiteralPath $rnsLogFile -Encoding UTF8
    } catch { Write-Warning 'Could not write startup launch timing.' }
}
$rnsExecutable = Join-Path $PSScriptRoot 'RetroNativeSaver.scr'
$rnsArguments = '/s'
if ($Windowed) {
    $rnsExecutable = Join-Path $PSScriptRoot 'RetroNativeSaver.exe'
    $rnsArguments = '--windowed'
}
if (-not (Test-Path -LiteralPath $rnsExecutable)) { throw "Build first: $rnsExecutable" }
$rnsStartInfo = New-Object Diagnostics.ProcessStartInfo
$rnsStartInfo.FileName = $rnsExecutable
$rnsStartInfo.Arguments = $rnsArguments
$rnsStartInfo.WorkingDirectory = $PSScriptRoot
$rnsStartInfo.UseShellExecute = $false
$rnsStartInfo.EnvironmentVariables['RNS_STARTUP_TIMING'] = '1'
Write-RnsLaunchEvent @{event='launch_request'; executable=$rnsExecutable; arguments=$rnsArguments}
$rnsLaunchClock = [Diagnostics.Stopwatch]::StartNew()
$rnsProcess = [Diagnostics.Process]::Start($rnsStartInfo)
try {
    $rnsLaunchClock.Stop()
    $rnsCreation = $null
    try { $rnsCreation = $rnsProcess.StartTime.ToUniversalTime().ToFileTimeUtc() } catch {}
    Write-RnsLaunchEvent @{event='launch_return'; target_pid=$rnsProcess.Id; creation_filetime=$rnsCreation; start_call_seconds=$rnsLaunchClock.Elapsed.TotalSeconds}
} finally { $rnsProcess.Dispose() }
Write-Host "Launch timing: $rnsLogFile"
