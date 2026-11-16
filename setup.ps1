<#
  setup.ps1: install the Stop AI Slop kit on Windows.

  What it does:
    1. Checks for Python 3.12 or newer.
    2. Creates a Python environment in .venv inside this folder.
    3. Installs the CPU build of PyTorch and the other libraries (about 1 GB).
    4. Installs the Claude Code skill to %USERPROFILE%\.claude\skills\editlens,
       with this folder's paths filled in. An existing skill there is backed up first.

  It does not download the model. That happens on the first scoring run,
  after you have Hugging Face access and have signed in (see README.md).

  Run from this folder:
    powershell -ExecutionPolicy Bypass -File .\setup.ps1
  Options:
    -NoSkill              skip installing the Claude Code skill
    -SkillsRoot <path>    install the skill somewhere other than ~\.claude\skills
    -RunsDir <path>       where the skill saves runs (default Documents\EditLens)
#>
param(
    [switch]$NoSkill,
    [string]$SkillsRoot = (Join-Path $HOME ".claude\skills"),
    [string]$RunsDir = (Join-Path ([Environment]::GetFolderPath("MyDocuments")) "EditLens")
)
$ErrorActionPreference = "Stop"
$kit = $PSScriptRoot

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }

Step "Checking Python"
$ver = & python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
if (-not $ver) { throw "Python was not found. Install Python 3.12 or newer from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'." }
$major, $minor = $ver.Split(".") | ForEach-Object { [int]$_ }
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 12)) { throw "Python $ver found. This kit needs 3.12 or newer." }
Write-Host "Python $ver"

Step "Creating the Python environment (.venv)"
$py = Join-Path $kit ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { & python -m venv (Join-Path $kit ".venv") }
& $py -m pip install --quiet --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }

Step "Installing PyTorch (CPU build) and libraries. This can take a few minutes."
& $py -m pip install --quiet torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw "PyTorch install failed." }
& $py -m pip install --quiet -r (Join-Path $kit "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Library install failed." }
& $py -c "import torch, transformers, peft; print('torch', torch.__version__, '| transformers', transformers.__version__, '| peft', peft.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw ("The libraries installed but would not load. If the error above mentions an 'Application Control policy', " +
        "Windows Smart App Control blocked a library file. Make sure requirements.txt is unchanged (its versions " +
        "are pinned for this reason), move the kit out of Downloads or Temp, delete .venv, and run setup.ps1 again.")
}

if (-not $NoSkill) {
    Step "Installing the Claude Code skill"
    $dest = Join-Path $SkillsRoot "editlens"
    New-Item -ItemType Directory -Force $dest | Out-Null
    New-Item -ItemType Directory -Force $RunsDir | Out-Null
    $target = Join-Path $dest "SKILL.md"
    if (Test-Path $target) {
        $bak = "$target.bak-" + (Get-Date -Format "yyyyMMdd-HHmmss")
        Copy-Item $target $bak
        Write-Host "Existing skill backed up to $bak"
    }
    $fwd = { param($p) $p -replace '\\', '/' }
    $text = Get-Content (Join-Path $kit "skill\editlens\SKILL.md") -Raw -Encoding UTF8
    $text = $text.Replace("{{PYTHON}}", (& $fwd $py)).Replace("{{KIT_DIR}}", (& $fwd $kit)).Replace("{{RUNS_DIR}}", (& $fwd $RunsDir))
    [IO.File]::WriteAllText($target, $text, (New-Object Text.UTF8Encoding($false)))
    Write-Host "Skill installed: $target"
    Write-Host "Runs will be saved under: $RunsDir"
}

Step "Done. Next steps"
Write-Host @"
1. If you have not already: accept the terms at https://huggingface.co/pangram/editlens_Llama-3.2-3B
   and request access at https://huggingface.co/meta-llama/Llama-3.2-3B
2. Sign in to Hugging Face (paste a Read token when asked):
     .\.venv\Scripts\hf.exe auth login
3. Test it (the first run downloads about 6 GB):
     .\.venv\Scripts\python.exe score.py --text "Paste a paragraph of your own writing here"
4. In Claude Code, start a new session, paste a draft and say "check this for AI".
"@
