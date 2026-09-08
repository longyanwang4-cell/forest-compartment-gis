param([string]$EnvDir="$env:USERPROFILE\.forest-gis-env")
$ErrorActionPreference='Stop';py -3 -m venv $EnvDir;& "$EnvDir\Scripts\python.exe" -m pip install --upgrade pip;& "$EnvDir\Scripts\python.exe" -m pip install -r (Join-Path (Split-Path $PSScriptRoot -Parent) 'requirements-segmentation.txt');Write-Host "环境已创建: $EnvDir"
