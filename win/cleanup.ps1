<#
.SYNOPSIS
    Remove everything this Windows setup created for ChatGarment.

.DESCRIPTION
    ChatGarment-main itself is kept: the script only deletes the artefacts that were
    added on top of the upstream checkout, so the source tree stays usable and every
    CG-WIN patch can still be inspected with "git diff".

    Deleted inside the repository
        .venv                python 3.11 virtual environment (~2.5 GB)
        .pip-cache           pip download cache used during the install
        .tmp                 TMP/TEMP for pip, torch and the tokenizer
        repos                GarmentCodeRC-main (sewing-pattern parser + assets)
        assets               junction -> repos\GarmentCodeRC-main\assets
        runs                 inference outputs produced by this setup
        Logs                 run logs (plain text)
        checkpoints          output_dir placeholder created by the eval script
        output               pygarment writes here when it does not use subfolders
        torchinductor_*      torch.compile / inductor cache written by torch 2.7
        .git                 optional, see -KeepGit
    Deleted outside the repository
        D:\ChatGarment_data  (~19 GB: the 14 GB checkpoint, the CLIP snapshot,
                              the llava config/tokenizer, torch wheels, pip cache)
                             see -KeepData

    Anything that is NOT listed here (including the upstream source tree, win\,
    llava\, scripts\, docs\, studio\*.py, studio\panel, studio\sim and this
    script) is never touched.

    Garment Studio (studio/) is an additive branch, so only its run-time folders are
    deleted: studio\jobs (one folder per design job) and studio\runs (smoke tests,
    server log).  The code, the panel and the Blender scripts stay; to uninstall the
    DSH sidebar plugin as well, run studio\dsh-plugin\install.ps1 -Uninstall.

.PARAMETER Execute
    Actually delete. Without it the script only prints what it would delete.

.PARAMETER KeepGit
    Keep .git (the baseline commit + the CG-WIN patch history).

.PARAMETER KeepData
    Keep D:\ChatGarment_data (the model weights), delete only the repo-local bits.

.PARAMETER DataRoot
    Where the big files live. Default: D:\ChatGarment_data

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File win\cleanup.ps1
    powershell -ExecutionPolicy Bypass -File win\cleanup.ps1 -Execute
    powershell -ExecutionPolicy Bypass -File win\cleanup.ps1 -Execute -KeepData -KeepGit
#>
[CmdletBinding()]
param(
    [switch]$Execute,
    [switch]$KeepGit,
    [switch]$KeepData,
    [string]$DataRoot = 'D:\ChatGarment_data'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $RepoRoot

$junk = @(
    '.venv', '.pip-cache', '.tmp', 'repos', 'runs', 'Logs', 'checkpoints', 'output',
    'studio\jobs', 'studio\runs', 'studio\_probe', 'studio\__pycache__'
)
$junk += 'assets'                       # junction: removed without touching its target
if (-not $KeepGit) { $junk += '.git' }
# torch.compile / inductor caches are named after the user, e.g. torchinductor_41239
$junk += @(Get-ChildItem -LiteralPath $RepoRoot -Directory -Force -Filter 'torchinductor_*' -ErrorAction SilentlyContinue |
           ForEach-Object { $_.Name })

Write-Host "repo root : $RepoRoot"
Write-Host "data root : $DataRoot"
Write-Host ('mode      : ' + $(if ($Execute) { 'EXECUTE' } else { 'dry run (add -Execute to delete)' }))
Write-Host ''

function Get-Size($p) {
    $items = Get-ChildItem -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
    $sum = ($items | Where-Object { -not $_.PSIsContainer } | Measure-Object -Property Length -Sum).Sum
    if ($null -eq $sum) { $sum = 0 }
    return $sum
}

function Remove-Tree($p, $label) {
    if (-not (Test-Path -LiteralPath $p)) {
        Write-Host ('  skip   {0,-28} (absent)' -f $label)
        return
    }
    $item = Get-Item -LiteralPath $p -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        # a junction / symlink: delete the link itself, never its target
        Write-Host ('  delete {0,-28} reparse point' -f $label)
        if ($Execute) { [System.IO.Directory]::Delete($p, $false) }
        return
    }
    if (-not $item.PSIsContainer) {
        Write-Host ('  delete {0,-28} {1,9:N1} MB' -f $label, ($item.Length / 1MB))
        if ($Execute) { Remove-Item -LiteralPath $p -Force }
        return
    }
    $size = Get-Size $p
    Write-Host ('  delete {0,-28} {1,9:N1} MB' -f $label, ($size / 1MB))
    if ($Execute) { Remove-Item -LiteralPath $p -Recurse -Force }
}

Write-Host "inside $RepoRoot"
foreach ($j in $junk) { Remove-Tree (Join-Path $RepoRoot $j) $j }

# things registered outside the repo: the Blender addon (if installed) and the DSH
# sidebar plugin (its cordis.patch.yml entry still has to go via install.ps1 -Uninstall)
$blenderBase = Join-Path $env:APPDATA 'Blender Foundation\Blender'
$blenderAddons = @(Get-ChildItem -LiteralPath $blenderBase -Directory -ErrorAction SilentlyContinue |
                   ForEach-Object { Join-Path $_.FullName 'scripts\addons\gcstudio' })
$dshPlugin = Join-Path $env:USERPROFILE '.dsh\profiles\web\node_modules\dsh-garment-studio'

if ($blenderAddons.Count -gt 0 -or (Test-Path -LiteralPath $dshPlugin)) {
    Write-Host ''
    Write-Host 'outside the repository'
    foreach ($b in $blenderAddons) { Remove-Tree $b ('Blender addon ' + (Split-Path $b -Parent)) }
    Remove-Tree $dshPlugin 'DSH plugin dsh-garment-studio'
}

if (-not $KeepData) {
    Write-Host ''
    Write-Host 'outside the repository'
    Remove-Tree $DataRoot $DataRoot
} else {
    Write-Host ''
    Write-Host ('  keep   {0} (-KeepData)' -f $DataRoot)
}

Write-Host ''
if ($Execute) {
    Write-Host 'done. ChatGarment-main source files were not touched.'
    Write-Host 'Note: the CG-WIN patches are plain edits in the source files; .git only holds their history.'
} else {
    Write-Host 'dry run only - re-run with -Execute to really delete.'
}
