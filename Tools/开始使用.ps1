# 森林小班GIS学生启动器：只收集必要参数，底层仍调用forest-gis.ps1。
param([switch]$DryRun)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms

function Select-Folder([string]$Title){
  $d=New-Object System.Windows.Forms.FolderBrowserDialog
  $d.Description=$Title
  $d.ShowNewFolderButton=$true
  if($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){ return $d.SelectedPath }
  return $null
}

Write-Host '=== 森林经理学实习 GIS 助手 ===' -ForegroundColor Green
$inputRoot=Select-Folder '选择老师提供的数据文件夹（请先解压）'
if(-not $inputRoot){ throw '未选择输入目录' }
$outputRoot=Select-Folder '选择成果保存目录（建议选择一个空文件夹）'
if(-not $outputRoot){ throw '未选择输出目录' }

$mode=Read-Host '执行模式 fast/standard/strict（直接回车=standard）'
if(-not $mode){$mode='standard'}
if($mode -notin @('fast','standard','strict')){throw '模式必须是 fast、standard 或 strict'}
$countText=Read-Host '预计候选小班数量（直接回车=20；已有小班时会自动采用实际数量）'
$count=20
if($countText){$count=[int]$countText}
$crs=Read-Host '工作坐标系，例如 EPSG:32652（不确定请向老师确认）'
if(-not $crs){throw '必须明确工作坐标系，不能由程序猜测'}
$demUnit=Read-Host 'DEM高程单位 METER/FOOT（直接回车=METER）'
if(-not $demUnit){$demUnit='METER'}
$zText=Read-Host '坡度计算z_factor（米制DEM直接回车=1.0）'
$z=1.0
if($zText){$z=[double]$zText}

$configPath=Join-Path $env:TEMP ('forest-gis-config-'+[guid]::NewGuid().ToString()+'.json')
$config=@{
  schema_version='1.1'; input_root=$inputRoot; output_root=$outputRoot; execution_mode=$mode
  input=@{imagery=$null;boundary=$null;dem=$null;compartments=$null}
  expected_compartment_count=$count; working_crs=$crs
  terrain=@{dem_z_unit=$demUnit;z_factor=$z;dem_cell_size=$null}
  segmentation=@{superpixels=650;compactness=8.0;max_pixels=50000000}
  naming=@{prefix='XB';start=1}
  package=@{enabled=$true;zip_output=$null}
  validation=@{overlap_tolerance_m2=1.0;gap_tolerance_m2=5.0;outside_tolerance_m2=1.0;min_coverage_ratio=0.999;require_projected_crs=$true;require_meter_unit=$true}
}|ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($configPath,$config,(New-Object System.Text.UTF8Encoding($false)))

$args=@('-NoProfile','-File',(Join-Path $PSScriptRoot 'forest-gis.ps1'),'-Action','prepare-practice','-InputRoot',$inputRoot,'-OutputRoot',$outputRoot,'-Config',$configPath,'-Mode',$mode)
if($DryRun){$args+='-DryRun'}
Write-Host "即将运行。临时配置会在本次执行后删除。" -ForegroundColor Cyan
$code=1
try {
  & powershell @args
  $code=$LASTEXITCODE
} finally {
  Remove-Item -LiteralPath $configPath -Force -ErrorAction SilentlyContinue
}
Write-Host "工作流退出码：$code" -ForegroundColor Yellow
if($code -eq 2){Write-Host '发现需要人工核查的问题，请查看03_Reports。修正后用forest-gis.ps1 -Resume继续。' -ForegroundColor Yellow}
elseif($code -eq 0){Write-Host '执行完成，请查看03_Reports\学生工作流报告.html。' -ForegroundColor Green}
Read-Host '按回车关闭'
exit $code
