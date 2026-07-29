param(
    [string]$SourceDirectory = ".tools/plantri/plantri58",
    [string]$OutputDirectory = ".tools/plantri/build"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$source = (Resolve-Path (Join-Path $repositoryRoot $SourceDirectory)).Path
$output = Join-Path $repositoryRoot $OutputDirectory
$patch = Join-Path $PSScriptRoot "windows-portability.patch"

New-Item -ItemType Directory -Force -Path $output | Out-Null
Copy-Item -LiteralPath (Join-Path $source "plantri.c") -Destination $output -Force
git apply --directory=$OutputDirectory $patch
if ($LASTEXITCODE -ne 0) { throw "Could not apply the Windows portability patch." }

python -m ziglang cc -O3 -std=c11 (Join-Path $output "plantri.c") -o (Join-Path $output "plantri.exe")
if ($LASTEXITCODE -ne 0) { throw "The plantri build failed." }

Get-FileHash -Algorithm SHA256 (Join-Path $output "plantri.exe")
