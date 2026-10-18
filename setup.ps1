<#
.SYNOPSIS
    One-time setup for a fresh clone: Python, the workspace venv, the pinned
    dependencies, and the browser tooling the run-magic skill drives.

.DESCRIPTION
    Safe to re-run. Every step checks for what it would install and skips it
    when it is already there, so a second run is a verification pass.

      1. Python   - the version CI runs (read out of .github/workflows/ci.yml),
                    installed per-user through winget when it is missing.
      2. .venv    - the workspace virtual environment every documented command
                    goes through (.\.venv\Scripts\python.exe).
      3. Packages - requirements.txt, which is pinned.
      4. Checks   - pip's own consistency check, the web app importing with the
                    whole card pool loaded, and the vocabulary catalogs.
      5. Browser  - Node.js and playwright-cli, for .claude/skills/run-magic.
                    Optional: a failure here is reported and does not fail the
                    setup, because nothing in the engine or the tests needs it.

    Run it through setup.cmd, which works whatever the machine's PowerShell
    execution policy is:

        .\setup.cmd
        .\setup.cmd -SkipBrowserTools
        .\setup.cmd -RunTests

.PARAMETER PythonVersion
    The major.minor to use. Defaults to the one ci.yml names, so a local run
    and a CI run are the same interpreter.

.PARAMETER Recreate
    Delete .venv and build it again, even if it already matches.

.PARAMETER SkipBrowserTools
    Do not install Node.js or playwright-cli.

.PARAMETER RunTests
    Finish with the full test suite, in parallel across as many workers as the
    machine's free memory will hold (python -m pytest -n <count>), or serially
    when it will hold only one.
#>
[CmdletBinding()]
param(
    [string]$PythonVersion,
    [switch]$Recreate,
    [switch]$SkipBrowserTools,
    [switch]$RunTests
)

$ErrorActionPreference = 'Stop'

$RepoRoot = $PSScriptRoot
$VenvDir = Join-Path $RepoRoot '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'

function Write-Step([string]$Message) {
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Note([string]$Message) {
    Write-Host "    $Message"
}

# A process started before an installer ran still has the old PATH, so the
# tool just installed is invisible to it. Re-read both halves from the registry.
function Update-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ';'
}

# The major.minor an interpreter reports, or $null if it will not run. The
# Microsoft Store alias in WindowsApps is a python.exe that prints an advert
# and exits 9009, so "is there a python on PATH" is not the question.
function Get-PythonMinorVersion([string]$Exe) {
    $ErrorActionPreference = 'SilentlyContinue'
    $global:LASTEXITCODE = 0
    try {
        $out = & $Exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    } catch {
        return $null
    }
    if ($LASTEXITCODE -ne 0 -or -not $out) {
        return $null
    }
    return "$out".Trim()
}

function Find-Python([string]$Version) {
    $candidates = @()
    $compact = $Version -replace '\.', ''

    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        $ErrorActionPreference = 'SilentlyContinue'
        try {
            $candidates += & $launcher.Source "-$Version" -c "import sys; print(sys.executable)" 2>$null
        } catch {
        }
        $ErrorActionPreference = 'Stop'
    }
    $candidates += Join-Path $env:LOCALAPPDATA "Programs\Python\Python$compact\python.exe"
    $candidates += Join-Path $env:ProgramFiles "Python$compact\python.exe"
    $candidates += Get-Command python.exe -All -ErrorAction SilentlyContinue |
        ForEach-Object { $_.Source }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            if ((Get-PythonMinorVersion $candidate) -eq $Version) {
                return $candidate
            }
        }
    }
    return $null
}

function Install-WithWinget([string]$Id, [string[]]$ExtraArguments) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw "winget is not available, so $Id cannot be installed automatically. Install it by hand and re-run setup."
    }
    $arguments = @(
        'install', '--id', $Id, '--exact', '--silent',
        '--accept-package-agreements', '--accept-source-agreements',
        '--disable-interactivity'
    ) + $ExtraArguments
    & winget.exe @arguments
    # winget's exit code is not checked: "already installed" is non-zero too.
    # Each caller looks for the tool itself afterwards, which is the real test.
    Update-ProcessPath
}

function Invoke-Checked([string]$What, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$What failed (exit code $LASTEXITCODE)."
    }
}

# How many pytest workers this machine can hold right now. `-n auto` starts one
# per logical core, and every worker is a whole interpreter that loads and
# collects the suite for itself - 2.5 GB before its first test, growing as it
# runs them: a serial run measured 3.6 GB half way and 4.5 GB at the end, and
# no worker of two or more runs more than half. Cores are not the limit on a machine
# with more of them than memory: twelve workers on 16 GB ran the commit charge
# out and the run stopped making progress at all. So the count is the smaller
# of the two, and one worker means a plain serial run rather than `-n 1`,
# which is the same work with a controller process on top.
$WorkerMemoryGb = 4
$MemoryMarginGb = 2

function Get-FreeMemoryGb {
    return (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB
}

function Get-TestWorkerCount {
    $byMemory = [Math]::Floor(((Get-FreeMemoryGb) - $MemoryMarginGb) / $WorkerMemoryGb)
    return [int][Math]::Max(1, [Math]::Min([Environment]::ProcessorCount, $byMemory))
}

function Install-BrowserTools {
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    if (-not $node) {
        Write-Note 'Node.js not found - installing the LTS release with winget.'
        Write-Note 'Its installer is machine-wide, so Windows will ask for permission.'
        Install-WithWinget 'OpenJS.NodeJS.LTS' @()
        $node = Get-Command node.exe -ErrorAction SilentlyContinue
        if (-not $node) {
            throw 'Node.js is still not on PATH after the winget install.'
        }
    }
    Write-Note "Node.js $(& $node.Source --version) at $($node.Source)"

    # npm.cmd by name: PowerShell would otherwise pick npm.ps1 beside it, which
    # a restricted execution policy refuses.
    $npm = Join-Path (Split-Path $node.Source) 'npm.cmd'
    $globalBin = Join-Path $env:APPDATA 'npm'
    $cli = Join-Path $globalBin 'playwright-cli.cmd'
    $onPath = Get-Command playwright-cli.cmd -ErrorAction SilentlyContinue
    if ($onPath) {
        $cli = $onPath.Source
    }
    if (-not (Test-Path $cli)) {
        Write-Note 'Installing playwright-cli (npm install -g @playwright/cli@latest).'
        Invoke-Checked 'npm install -g @playwright/cli' { & $npm install -g '@playwright/cli@latest' }
        $prefix = (& $npm prefix -g)
        if ($prefix) {
            $globalBin = "$prefix".Trim()
            $cli = Join-Path $globalBin 'playwright-cli.cmd'
        }
        if (-not (Test-Path $cli)) {
            throw "playwright-cli.cmd was not found in $globalBin after the npm install."
        }
    }
    Write-Note "playwright-cli $(& $cli --version) at $cli"

    Update-ProcessPath
    if (-not (Get-Command playwright-cli.cmd -ErrorAction SilentlyContinue)) {
        Write-Warning "$(Split-Path $cli) is not on PATH. Add it, or call '$cli' directly."
    }
    Write-Note 'It downloads its own Chromium the first time it opens a page.'
}

Push-Location $RepoRoot
try {
    # --- 1. Python -----------------------------------------------------------
    if (-not $PythonVersion) {
        $workflow = Join-Path $RepoRoot '.github\workflows\ci.yml'
        $match = Select-String -Path $workflow -Pattern "python-version:\s*['""]?(\d+\.\d+)" |
            Select-Object -First 1
        if (-not $match) {
            throw "Could not read python-version out of $workflow. Pass -PythonVersion."
        }
        $PythonVersion = $match.Matches[0].Groups[1].Value
    }
    Write-Step "Python $PythonVersion (the version CI runs)"

    $python = Find-Python $PythonVersion
    if (-not $python) {
        Write-Note 'Not found - installing for the current user with winget.'
        Install-WithWinget "Python.Python.$PythonVersion" @('--scope', 'user')
        $python = Find-Python $PythonVersion
        if (-not $python) {
            throw "Python $PythonVersion is still not found after the winget install. Install it from https://www.python.org/downloads/ and re-run setup."
        }
    }
    Write-Note "Using $python"

    # --- 2. The virtual environment ------------------------------------------
    Write-Step 'Virtual environment (.venv)'
    if (Test-Path $VenvDir) {
        $existing = $null
        if (Test-Path $VenvPython) {
            $existing = Get-PythonMinorVersion $VenvPython
        }
        if ($Recreate) {
            Write-Note 'Removing the existing .venv (-Recreate).'
            Remove-Item -Recurse -Force $VenvDir
        } elseif ($existing -ne $PythonVersion) {
            if ($existing) {
                $found = "is Python $existing"
            } else {
                $found = 'has no working interpreter'
            }
            throw ".venv already exists and $found, not Python $PythonVersion. Re-run with -Recreate to rebuild it."
        } else {
            Write-Note "Already present on Python $existing - reusing it."
        }
    }
    if (-not (Test-Path $VenvPython)) {
        Invoke-Checked 'Creating .venv' { & $python -m venv $VenvDir }
        Write-Note "Created $VenvDir"
    }

    # --- 3. Dependencies ------------------------------------------------------
    Write-Step 'Dependencies (requirements.txt)'
    Invoke-Checked 'Upgrading pip' { & $VenvPython -m pip install --quiet --upgrade pip }
    Invoke-Checked 'Installing requirements.txt' {
        & $VenvPython -m pip install --disable-pip-version-check -r requirements.txt
    }

    # --- 4. Checks ------------------------------------------------------------
    Write-Step 'Checking the environment'
    Invoke-Checked 'pip check' { & $VenvPython -m pip check }
    # Importing web.app builds the FastAPI app and loads every set in
    # cards/manifest.json, so it fails here rather than at the first request.
    Invoke-Checked 'Importing the web app' {
        & $VenvPython -c "import web.app; from web.runtime import CARD_CATALOG; print('web app imports; %d cards loaded' % len(CARD_CATALOG))"
    }
    Invoke-Checked 'Vocabulary catalogs' { & $VenvPython scripts/fetch_vocabulary.py --check }

    # --- 5. Browser tooling (optional) ---------------------------------------
    $browserStatus = 'skipped (-SkipBrowserTools)'
    if (-not $SkipBrowserTools) {
        Write-Step 'Browser tooling for the run-magic skill (Node.js + playwright-cli)'
        try {
            Install-BrowserTools
            $browserStatus = 'installed'
        } catch {
            $browserStatus = "NOT installed - $($_.Exception.Message)"
            Write-Warning $browserStatus
            Write-Warning 'The engine, the web app and the tests do not need it; re-run setup to try again.'
        }
    }

    # --- 6. The suite, on request ---------------------------------------------
    $workers = Get-TestWorkerCount
    $pytestArguments = @('-m', 'pytest')
    if ($workers -gt 1) {
        $pytestArguments += @('-n', "$workers")
    }
    $pytestCommand = "python $($pytestArguments -join ' ')"
    if ($RunTests) {
        Write-Step "Test suite ($pytestCommand)"
        Invoke-Checked 'The test suite' { & $VenvPython @pytestArguments }
    }

    Write-Step 'Setup complete'
    Write-Note "Python:        $(& $VenvPython --version) in .venv"
    Write-Note "Browser tools: $browserStatus"
    Write-Host ''
    Write-Note 'Next:'
    Write-Note "  .\.venv\Scripts\python.exe $($pytestArguments -join ' ')"
    $cores = [Environment]::ProcessorCount
    if ($workers -lt $cores) {
        $freeGb = [Math]::Round((Get-FreeMemoryGb), 1)
        Write-Note "      (not -n auto: that is $cores workers at about $WorkerMemoryGb GB each, and $freeGb GB is free)"
    }
    Write-Note '  .\.venv\Scripts\python.exe -m uvicorn web.app:app --host 127.0.0.1 --port 8010'
    Write-Note '  then open http://127.0.0.1:8010/'
} finally {
    Pop-Location
}
