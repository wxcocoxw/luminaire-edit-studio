# SPDX-License-Identifier: GPL-3.0-only
param([Parameter(Mandatory=$true)][string]$ComfyRoot,[string]$Pack='qwen21')
$ErrorActionPreference='Stop'
$sourceRoot=[IO.Path]::GetFullPath($PSScriptRoot)
$resolvedRoot=(Resolve-Path -LiteralPath $ComfyRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $resolvedRoot 'main.py'))) { throw 'Choose the inner ComfyUI directory containing main.py.' }
$portablePython=Join-Path (Split-Path -Parent $resolvedRoot) 'python_embeded\python.exe'
if (-not (Test-Path -LiteralPath $portablePython)) { throw 'This helper targets Windows Portable. Follow README.md for a manual install on other setups.' }
function Resolve-SourceFile([string]$Relative) {
 if ([IO.Path]::IsPathRooted($Relative)) { throw 'Source paths must be relative.' }
 $absolute=[IO.Path]::GetFullPath((Join-Path $sourceRoot $Relative))
 if (-not $absolute.StartsWith($sourceRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Source path escaped the release directory.' }
 if (-not (Test-Path -LiteralPath $absolute -PathType Leaf)) { throw "Missing release file: $Relative" }
 return $absolute
}
$workspace=Get-Content -LiteralPath (Resolve-SourceFile 'workspace_manifest.json') -Raw | ConvertFrom-Json
if ($Pack -notmatch '^[a-z0-9_-]+$') { throw 'Invalid workflow-pack ID.' }
$entries=@($workspace.packs | Where-Object { $_.id -ceq $Pack })
if ($entries.Count -ne 1) { throw "Unknown workflow pack: $Pack" }
$packConfig=Get-Content -LiteralPath (Resolve-SourceFile ([string]$entries[0].manifest)) -Raw | ConvertFrom-Json
if ($packConfig.id -cne $Pack -or $packConfig.status -cne 'supported') { throw 'Workflow pack is not supported.' }
$version=[string]$packConfig.version
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid workflow-pack version.' }
$workflowSource=Resolve-SourceFile ([string]$packConfig.workflow)
$customRoot=Join-Path $resolvedRoot 'custom_nodes'
if ($sourceRoot.StartsWith([IO.Path]::GetFullPath($customRoot)+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'This repository is already inside custom_nodes. Restart ComfyUI and import its workflow; do not install a second copy.' }
$extensionTarget=Join-Path $customRoot 'ComfyUI-LuminaireEditStudio'
$workflowTarget=Join-Path $resolvedRoot "user\default\workflows\Luminaire Edit Studio\LUMINAIRE_$($Pack.ToUpperInvariant())_v$version.json"
foreach ($name in @('ComfyUI-LuminaireEditStudio','luminaire-edit-studio','ComfyUI-QwenStudio','qwen-studio')) {
 if (Test-Path -LiteralPath (Join-Path $customRoot $name)) { throw "$name already exists. Back it up outside custom_nodes before replacing it; keep one runtime copy." }
}
if (Test-Path -LiteralPath $workflowTarget) { throw 'The versioned workflow already exists. No files were changed.' }
$running=Get-Process -Name python,pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $portablePython }
if ($running) { throw 'Close ComfyUI and other processes using its bundled Python first.' }
$runtimeFiles=@($workspace.shared_runtime_files)+@($packConfig.runtime_files)+@('SOURCES.md','LICENSE','NOTICE.md',
 'licenses/Comfy-Workflow-Templates-MIT.txt','docs/MODEL_LICENSES.md')
foreach ($relative in $runtimeFiles) {
 $null=Resolve-SourceFile ([string]$relative)
}
$staging=Join-Path $resolvedRoot ('user\luminaire-studio-staging\'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $staging -Force | Out-Null
foreach ($relative in $runtimeFiles) {
 $destination=Join-Path $staging $relative
 New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
 Copy-Item -LiteralPath (Join-Path $sourceRoot $relative) -Destination $destination
}
# Both absolute move targets must remain inside the explicitly selected ComfyUI root.
foreach ($target in @($staging,$extensionTarget)) {
 if (-not [IO.Path]::GetFullPath($target).StartsWith([IO.Path]::GetFullPath($resolvedRoot)+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Install path escaped the selected ComfyUI directory.' }
}
New-Item -ItemType Directory -Path $customRoot,(Split-Path -Parent $workflowTarget) -Force | Out-Null
Move-Item -LiteralPath $staging -Destination $extensionTarget
Copy-Item -LiteralPath $workflowSource -Destination $workflowTarget
Write-Output "Installed runtime: $extensionTarget"
Write-Output "Installed workflow: $workflowTarget"
Write-Output "Workflow pack: $($packConfig.display_name)"
Write-Output 'Restart ComfyUI, refresh its browser tab, and load the new workflow. No Python packages or launch flags were changed.'
