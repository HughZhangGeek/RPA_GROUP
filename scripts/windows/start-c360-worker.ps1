param(
    [string]$WorkDir = "C:\rpa_work\RPA_GROUP"
)

$ErrorActionPreference = "Stop"

function Resolve-WorkerPython {
    if ($env:RPA_PYTHON) {
        if (Test-Path -LiteralPath $env:RPA_PYTHON) {
            return @{ Command = $env:RPA_PYTHON; Args = @() }
        }
        throw "RPA_PYTHON is set but not found: $env:RPA_PYTHON"
    }

    $candidates = @()
    if ($env:CONDA_PREFIX) {
        if ((Split-Path -Leaf $env:CONDA_PREFIX) -eq "RPA_GROUP") {
            $candidates += (Join-Path $env:CONDA_PREFIX "python.exe")
        }
        $candidates += (Join-Path $env:CONDA_PREFIX "envs\RPA_GROUP\python.exe")
    }

    $candidates += @(
        "$env:USERPROFILE\miniconda3\envs\RPA_GROUP\python.exe",
        "$env:USERPROFILE\anaconda3\envs\RPA_GROUP\python.exe",
        "C:\ProgramData\miniconda3\envs\RPA_GROUP\python.exe",
        "C:\ProgramData\anaconda3\envs\RPA_GROUP\python.exe",
        "C:\Miniconda3\envs\RPA_GROUP\python.exe",
        "C:\Anaconda3\envs\RPA_GROUP\python.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return @{ Command = $candidate; Args = @() }
        }
    }

    $conda = Get-Command conda -ErrorAction SilentlyContinue
    if ($conda) {
        return @{ Command = "conda"; Args = @("run", "--no-capture-output", "-n", "RPA_GROUP", "python") }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @{ Command = $python.Source; Args = @() }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @{ Command = $py.Source; Args = @("-3") }
    }

    throw @"
Python was not found.

Fix options:
1. Add python to PATH for this Windows user.
2. Install/activate the RPA_GROUP conda environment.
3. Set RPA_PYTHON in .local\rpa-worker-env.ps1, for example:
   `$env:RPA_PYTHON = "C:\ProgramData\miniconda3\envs\RPA_GROUP\python.exe"
"@
}

if (-not (Test-Path -LiteralPath $WorkDir)) {
    throw "RPA workdir not found: $WorkDir"
}

Set-Location -LiteralPath $WorkDir

$envFile = Join-Path $WorkDir ".local\rpa-worker-env.ps1"
if (-not (Test-Path -LiteralPath $envFile)) {
    throw "Missing env file: $envFile"
}

. $envFile
$env:PYTHONIOENCODING = "utf-8"

$resolved = Resolve-WorkerPython
Write-Host "[INFO] Using Python command: $($resolved.Command) $($resolved.Args -join ' ')"

$probeCode = "import importlib.util, sys; print('[INFO] Python executable: ' + sys.executable); sys.exit(0 if (importlib.util.find_spec('websockets') or importlib.util.find_spec('aiohttp')) else 42)"
$probeArgs = @($resolved.Args) + @("-c", $probeCode)
& $resolved.Command @probeArgs
if ($LASTEXITCODE -ne 0) {
    throw "Selected Python cannot import websockets or aiohttp. Make sure the RPA_GROUP conda env is selected, or install worker WSS dependencies in that env."
}

$workerArgs = @($resolved.Args) + @("-m", "rpa_platform.worker.c360_worker", "--verbose")
& $resolved.Command @workerArgs
exit $LASTEXITCODE
