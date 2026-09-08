param([string]$InstallDir,[string]$Propy,[string]$ProExe)
$ErrorActionPreference='Stop'
if(-not $Propy){$c=@("$env:ProgramFiles\ArcGIS\Pro\bin\Python\scripts\propy.bat",'C:\ArcGIS\Pro\bin\Python\scripts\propy.bat','D:\ArcGIS\Pro\bin\Python\scripts\propy.bat','D:\Program Files\ArcGIS\Pro\bin\Python\scripts\propy.bat');$Propy=$c|Where-Object{Test-Path $_}|Select-Object -First 1}
if(-not $Propy){$Propy=Read-Host '请粘贴propy.bat完整路径'}
if(-not(Test-Path $Propy)){throw '路径不存在'}
if(-not $InstallDir){$InstallDir=Split-Path (Split-Path (Split-Path (Split-Path $Propy -Parent)-Parent)-Parent)-Parent}
if(-not $ProExe){$ProExe=Join-Path $InstallDir 'bin\ArcGISPro.exe'}
[Environment]::SetEnvironmentVariable('ARCGIS_PRO_ROOT',$InstallDir,'User');[Environment]::SetEnvironmentVariable('ARCGIS_PROPY',$Propy,'User');[Environment]::SetEnvironmentVariable('ARCGIS_PRO_EXE',$ProExe,'User');Write-Host '配置成功，请重启WorkBuddy。'
