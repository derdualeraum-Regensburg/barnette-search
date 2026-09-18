param(
    [Parameter(Mandatory = $true)][string]$RunRoot,
    [ValidateSet('Start', 'Pause', 'Resume', 'Status')][string]$Action = 'Status'
)
$ErrorActionPreference = 'Stop'
$RunRoot = (Resolve-Path -LiteralPath $RunRoot).Path
$workRoot = Join-Path $RunRoot 'work'
$statusPath = Join-Path $workRoot 'status.json'
$state = $null
$controller = $null
if (Test-Path -LiteralPath $statusPath) {
    $state = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    $candidate = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
    if ($candidate) {
        $created = ([DateTimeOffset]$candidate.StartTime.ToUniversalTime()).ToUnixTimeMilliseconds() / 1000.0
        if ([Math]::Abs($created - $state.process_created) -lt 0.01) { $controller = $candidate }
    }
}
if ($Action -eq 'Status') {
    if ($state) {
        $state | Format-List
        Write-Output ('Controller aktiv: ' + [bool]$controller)
        $done = @(Get-ChildItem -LiteralPath (Join-Path $workRoot 'completed') -Filter '*.json' -ErrorAction SilentlyContinue)
        Write-Output ('Abgeschlossene Arbeitsschritte: ' + $done.Count)
    } else { Write-Output 'Noch nicht gestartet.' }
    return
}
if ($Action -eq 'Pause') {
    if (-not $controller) {
        Write-Output 'Kein aktiver Controller. Der gespeicherte Stand bleibt erhalten.'
        return
    }
    New-Item -ItemType File -Force -Path (Join-Path $workRoot 'PAUSE') | Out-Null
    if (-not $controller.WaitForExit(45000)) {
        throw 'Pause angefordert; der Controller ist noch aktiv. Vor dem Fortsetzen status.ps1 aufrufen.'
    }
    $state = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    Write-Output ('Controller beendet. Status: ' + $state.status)
    return
}
if ($controller) { throw ('Berechnung laeuft bereits, PID ' + $controller.Id) }
$configuration = Join-Path $workRoot 'configuration.json'
if (($Action -eq 'Start') -and (Test-Path -LiteralPath $configuration)) {
    throw 'Gespeicherter Lauf vorhanden. Bitte resume.ps1 verwenden.'
}
$plan = Get-Content -LiteralPath (Join-Path $RunRoot 'RUN_PLAN.json') -Raw | ConvertFrom-Json
$pythonExe = $plan.python_executable
# Check the frozen inputs before launching or resuming any calculation.
foreach ($line in Get-Content -LiteralPath (Join-Path $RunRoot 'PREPARATION_SHA256SUMS.txt')) {
    $parts = $line -split '  ', 2
    $actual = (Get-FileHash -LiteralPath (Join-Path $RunRoot $parts[1]) -Algorithm SHA256).Hash
    if ($actual -ne $parts[0]) { throw ('Vorbereitungsdatei veraendert: ' + $parts[1]) }
}
$driver = Join-Path $RunRoot 'source/tools/recalculate_certificates.py'
$plantriExe = Join-Path $RunRoot 'toolchain/plantri.exe'
$runArguments = @('-u', $driver, '--root', $workRoot, '--plantri', $plantriExe, '--workers', [string]$plan.workers)
if ($Action -eq 'Resume') { $runArguments += '--resume' }
$argumentLine = ($runArguments | ForEach-Object { '"' + $_ + '"' }) -join ' '
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$stdout = Join-Path $RunRoot ('controller-' + $stamp + '.stdout.log')
$stderr = Join-Path $RunRoot ('controller-' + $stamp + '.stderr.log')
$oldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $RunRoot 'source/src'
    $process = Start-Process -FilePath $pythonExe -ArgumentList $argumentLine -WorkingDirectory $RunRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    if (-not $process.HasExited) { $process.PriorityClass = 'BelowNormal' }
    if ($process.WaitForExit(1500)) {
        Get-Content -LiteralPath $stderr
        throw ('Controller bereits beendet, Exit-Code ' + $process.ExitCode)
    }
    Write-Output ('Controller PID: ' + $process.Id)
    Write-Output ('Status: ' + $statusPath)
    Write-Output ('Protokoll: ' + $stdout)
} finally { $env:PYTHONPATH = $oldPythonPath }
