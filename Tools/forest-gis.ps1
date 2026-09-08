param(
  [Parameter(Mandatory=$true)]
  [ValidateSet('doctor','inspect','segment','build-data','project','validate','package','plan','prepare-practice','tools','benchmark')]
  [string]$Action,
  [string]$InputRoot,
  [string]$OutputRoot,
  [string]$Config,
  [string]$ZipOutput,
  [string]$Gpkg,
  [string]$PythonExe,
  [string]$PropyBat,
  [string]$RequestJson,
  [ValidateSet('universal','codex')]
  [string]$Platform='universal',
  [string]$PlanOutput,
  [Nullable[int]]$ExpectedCompartmentCount,
  [string]$WorkingCrs,
  [string]$DemZUnit,
  [Nullable[double]]$ZFactor,
  [Nullable[double]]$DemCellSize,
  [switch]$Resume,
  [switch]$Revalidate,
  [switch]$SkipPackage,
  [ValidateSet('fast','standard','strict')]
  [string]$Mode='standard',
  [switch]$DryRun,
  [switch]$ApproveCandidates
)
$ErrorActionPreference='Stop'
# 让子进程 Python 使用 UTF-8，避免 GBK 控制台编码导致非 GBK 字符（如 m²）打印时 UnicodeEncodeError
$env:PYTHONUTF8='1'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$Root=Split-Path $PSScriptRoot -Parent
$Common=Join-Path $Root 'scripts\common'
$Pro=Join-Path $Root 'scripts\arcgis_pro'

# 已保存配置：放在用户目录而非 Skill 安装目录，避免重新导入/升级后丢失
$SavedEnvJson = Join-Path $env:USERPROFILE '.forest-gis\python_env.json'

$script:_PlainCache = @{}
$script:_Propy = $null

function Get-RequiredModules([string]$Action){
  # 按动作返回普通 Python 所需依赖模块；不强制所有动作用完整分割环境
  switch($Action){
    'inspect'  { return @('fiona','rasterio') }
    'validate' { return @('geopandas','rasterio','shapely','numpy') }
    'segment'  { return @('geopandas','rasterio','shapely','numpy','scipy','skimage','sklearn') }
    'prepare-practice' { return @('geopandas','rasterio','shapely','numpy','scipy','skimage','sklearn') }
    default    { return @() }   # doctor / package / 其他：仅 Python 3
  }
}

function Test-PlainPython([string]$ExePath,[string[]]$Prefix,[string[]]$Modules){
  # 只读探测：exe 存在 且 能 import 所需模块；模块为空则仅验证 Python 3 可运行
  if(-not $ExePath -or -not (Test-Path $ExePath)){ return $false }
  if($Modules -and $Modules.Count -gt 0){ $code='import '+($Modules -join ',') }
  else { $code='import sys; assert sys.version_info[0]>=3' }
  & $ExePath @Prefix -c $code 2>$null
  return ($LASTEXITCODE -eq 0)
}

function Get-SavedConfig([string]$Key){
  if(Test-Path $SavedEnvJson){
    try{
      $cfg = Get-Content $SavedEnvJson -Raw -Encoding UTF8 | ConvertFrom-Json
      $v = $cfg.$Key
      if($v){ return [string]$v }
    } catch {}
  }
  return $null
}

function Resolve-PlainPython([string[]]$Modules){
  $key = ($Modules -join ',')
  if($script:_PlainCache.ContainsKey($key)){ return $script:_PlainCache[$key] }

  # a) 显式 -PythonExe
  if($PythonExe){
    if(Test-PlainPython $PythonExe @() $Modules){ return ($script:_PlainCache[$key]=@{Exe=$PythonExe;Prefix=@()}) }
    throw "指定的 -PythonExe 未通过依赖探测（需 import $key）: $PythonExe"
  }
  # b) 环境变量 FOREST_GIS_PYTHON
  if($env:FOREST_GIS_PYTHON){
    if(Test-PlainPython $env:FOREST_GIS_PYTHON @() $Modules){ return ($script:_PlainCache[$key]=@{Exe=$env:FOREST_GIS_PYTHON;Prefix=@()}) }
    throw "FOREST_GIS_PYTHON 指定的解释器未通过依赖探测（需 import $key）: $env:FOREST_GIS_PYTHON"
  }
  # c) 已保存配置
  $saved = Get-SavedConfig 'plain_python'
  if($saved){
    if(Test-PlainPython $saved @() $Modules){ return ($script:_PlainCache[$key]=@{Exe=$saved;Prefix=@()}) }
    throw "已保存配置的普通 Python 未通过依赖探测（需 import $key）: $saved"
  }
  # d) 自动发现候选（每个都做依赖探测）；顺序：venv -> PATH python -> py -3 -> 常见 Anaconda/Miniconda
  $checked=@(); $cands=@()
  $cands += @{Exe=(Join-Path $env:USERPROFILE '.forest-gis-env\Scripts\python.exe');Prefix=@();Label='skill venv'}
  $pyc = Get-Command python -ErrorAction SilentlyContinue
  if($pyc){ $cands += @{Exe=$pyc.Source;Prefix=@();Label='python (PATH)'} }
  $py = Get-Command py -ErrorAction SilentlyContinue
  if($py){ $cands += @{Exe=$py.Source;Prefix=@('-3');Label='py -3'} }
  foreach($ap in @("$env:USERPROFILE\anaconda3\python.exe","$env:USERPROFILE\miniconda3\python.exe","$env:USERPROFILE\AppData\Local\Continuum\anaconda3\python.exe","C:\ProgramData\Anaconda3\python.exe","C:\ProgramData\Miniconda3\python.exe","D:\Anaconda3\python.exe","D:\Miniconda3\python.exe")){
    if(Test-Path $ap){ $cands += @{Exe=$ap;Prefix=@();Label='anaconda/miniconda'} }
  }
  foreach($c in $cands){
    $checked += "$($c.Label) -> $($c.Exe)"
    if(Test-PlainPython $c.Exe $c.Prefix $Modules){ return ($script:_PlainCache[$key]=@{Exe=$c.Exe;Prefix=$c.Prefix}) }
  }
  throw "未找到满足依赖（需 import $key）的普通 Python。已检查: $($checked -join '; ')。请用 -PythonExe 指定，或设 FOREST_GIS_PYTHON，或运行 Tools\setup_segmentation_env.ps1。"
}

function Resolve-Propy{
  if($script:_Propy){ return $script:_Propy }

  # a) 显式 -PropyBat
  if($PropyBat){
    if(-not (Test-Path $PropyBat)){ throw "指定的 -PropyBat 不存在: $PropyBat" }
    if(-not (Test-ArcPy $PropyBat)){ throw "指定的 -PropyBat 探测 import arcpy 失败: $PropyBat（不安装/不修复 ArcPy）" }
    return ($script:_Propy=$PropyBat)
  }
  # b) 环境变量 ARCGIS_PROPY
  if($env:ARCGIS_PROPY -and (Test-Path $env:ARCGIS_PROPY)){
    if(Test-ArcPy $env:ARCGIS_PROPY){ return ($script:_Propy=$env:ARCGIS_PROPY) }
  }
  # c) 已保存配置
  $saved = Get-SavedConfig 'propy'
  if($saved -and (Test-Path $saved)){
    if(Test-ArcPy $saved){ return ($script:_Propy=$saved) }
  }
  # d) ArcGIS Pro 默认安装路径
  $defaults = @("$env:ProgramFiles\ArcGIS\Pro\bin\Python\scripts\propy.bat",
                'C:\ArcGIS\Pro\bin\Python\scripts\propy.bat',
                'D:\ArcGIS\Pro\bin\Python\scripts\propy.bat',
                'D:\Program Files\ArcGIS\Pro\bin\Python\scripts\propy.bat')
  $checked = @($defaults)
  if($env:ARCGIS_PROPY){ $checked += $env:ARCGIS_PROPY }
  if($saved){ $checked += $saved }
  foreach($p in $defaults){
    if(Test-Path $p){
      if(Test-ArcPy $p){ return ($script:_Propy=$p) }
      else { throw "探测到 propy.bat 但 import arcpy 失败: $p（不安装/不修复 ArcPy）" }
    }
  }
  throw "未找到可用的 propy.bat（需能 import arcpy）。已检查: $($checked -join '; ')。请用 -PropyBat 指定，或运行 Tools\配置ArcGISPro路径.ps1，或设 ARCGIS_PROPY。"
}

function Quote-CmdArgument([string]$Value){
  # 为 cmd.exe 命令行参数添加外层双引号，保证空格/中文/括号/单引号/路径分隔符安全传递。
  # 不支持包含换行或未转义双引号的参数，遇到直接报错。
  if($null -eq $Value){ return '""' }
  if($Value -match "[`r`n]"){
    throw "命令参数不能包含换行"
  }
  if($Value.Contains('"')){
    throw "命令参数包含未支持的双引号: $Value"
  }
  # cmd.exe 会在双引号内仍展开 %VAR%。为防环境变量注入，拒绝百分号。
  if($Value.Contains('%')){
    throw "命令参数不能包含百分号（cmd.exe 环境变量展开风险）: $Value"
  }
  if($Value.IndexOf([char]0) -ge 0){
    throw "命令参数不能包含 NUL 字符"
  }
  return '"' + $Value + '"'
}

function Invoke-Propy(
  [string]$BatchPath,
  [string[]]$Arguments,
  [string]$Kind
){
  # 通过 cmd.exe 调用 .bat，使用 Start-Process -Wait -PassThru 获取真实进程退出码。
  # 避免 PS 直接 & .bat 时 cmd.exe 链条导致 LASTEXITCODE 误判。
  # 所有参数经 Quote-CmdArgument 安全引用。
  if(-not (Test-Path -LiteralPath $BatchPath)){
    throw "${Kind}: propy.bat 不存在: ${BatchPath}"
  }

  $quotedBatch = Quote-CmdArgument $BatchPath
  $quotedArgs = @(
    $Arguments | ForEach-Object {
      Quote-CmdArgument ([string]$_)
    }
  )

  $innerCommand = $quotedBatch
  if($quotedArgs.Count -gt 0){
    $innerCommand += ' ' + ($quotedArgs -join ' ')
  }

  # cmd /s 去除外层引号后解析内部命令；/v:off 关闭延迟变量展开避免 ! 干扰
  $cmdArguments =
    '/d /s /v:off /c "' + $innerCommand + '"'

  $outFile = [System.IO.Path]::GetTempFileName()
  $errFile = [System.IO.Path]::GetTempFileName()

  try {
    $proc = Start-Process `
      -FilePath $env:ComSpec `
      -ArgumentList $cmdArguments `
      -NoNewWindow `
      -Wait `
      -PassThru `
      -RedirectStandardOutput $outFile `
      -RedirectStandardError $errFile

    $code = $proc.ExitCode

    $out = Get-Content $outFile `
      -Encoding UTF8 `
      -ErrorAction SilentlyContinue

    $err = Get-Content $errFile `
      -Raw `
      -Encoding UTF8 `
      -ErrorAction SilentlyContinue

    if($code -ne 0){
      $message =
        "$Kind 执行失败：interpreter=$BatchPath exit=$code"
      if($err){
        $message += "`n" + $err.Trim()
      }
      throw $message
    }

    return $out
  }
  finally {
    Remove-Item $outFile,$errFile `
      -Force `
      -ErrorAction SilentlyContinue
  }
}

function Test-ArcPy([string]$PropyPath){
  # 只读探测 import arcpy；成功才返回 true。不安装、不修复。
  # 复用 Invoke-Propy 避免重复 Start-Process 逻辑。
  try {
    $null = Invoke-Propy $PropyPath @(
      '-c',
      "import arcpy; print(arcpy.GetInstallInfo().get('Version'))"
    ) 'ArcPy探测'
    return $true
  }
  catch {
    return $false
  }
}

function Invoke-Native([string]$Exe,[string[]]$Prefix,[string]$Script,[string[]]$ScriptArgs,[string]$Kind){
  # 把 stderr 重定向到临时文件，避免 PS5.1 + EAP=Stop 把子进程 stderr 变成终止性 NativeCommandError；
  # 退出码非 0 时 throw，含解释器/脚本/退出码/stderr。
  $errFile = [System.IO.Path]::GetTempFileName()
  $out = $null; $code = 0
  try {
    $out = & $Exe @Prefix $Script @ScriptArgs 2>$errFile
    $code = $LASTEXITCODE
  } finally {
    $errText = ''
    if(Test-Path $errFile){ try{ $errText = (Get-Content $errFile -Raw -ErrorAction SilentlyContinue) } catch {} }
    Remove-Item $errFile -Force -ErrorAction SilentlyContinue
  }
  if($code -ne 0){
    $msg = "${Kind} 脚本执行失败: interpreter=$Exe script=$Script exit=$code"
    if($errText){ $msg += "`n" + $errText.Trim() }
    throw $msg
  }
  return $out
}

function Run-Python([string]$Script,[string[]]$ScriptArgs){
  $py = Resolve-PlainPython (Get-RequiredModules $Action)
  return Invoke-Native $py.Exe $py.Prefix $Script $ScriptArgs 'Python'
}

function Run-ArcPy(
  [string]$Script,
  [string[]]$ScriptArgs
){
  $propy = Resolve-Propy
  return Invoke-Propy `
    $propy `
    (@($Script) + $ScriptArgs) `
    'ArcPy'
}

if($Action -eq 'tools'){
  Run-Python (Join-Path $Common 'list_tools.py') @()
}
if($Action -eq 'benchmark'){
  $benchOut = if($OutputRoot){ Join-Path $OutputRoot 'benchmark_report.json' } else { Join-Path (Join-Path $Root 'benchmarks') 'benchmark_report.json' }
  Run-Python (Join-Path $Common 'run_benchmark.py') @('--output',$benchOut)
}
if($Action -eq 'plan'){
  # v1.2.0-dev 通用控制层：只生成可审计执行计划，不运行 GIS 业务脚本。
  if(-not $RequestJson){throw '需要-RequestJson'}
  $planArgs = @('--platform',$Platform,'--request',$RequestJson)
  if($PlanOutput){ $planArgs += @('--output',$PlanOutput) }
  Run-Python (Join-Path $Common 'plan_command.py') $planArgs
}
if($Action -eq 'doctor'){
  Run-Python (Join-Path $Common 'detect_gis.py') @('--json')
}
if($Action -eq 'inspect'){
  if(-not $InputRoot){throw '需要-InputRoot'}
  if(-not $OutputRoot){
    $inputResolved = (Resolve-Path -LiteralPath $InputRoot).Path
    $parent = Split-Path $inputResolved -Parent
    $leaf = Split-Path $inputResolved -Leaf
    $OutputRoot = Join-Path $parent ($leaf + '_forest_gis_check')
  }
  # inspect_inputs.py validates that the report path is outside the input tree
  # before creating its parent directory. Do not create it earlier here.
  Run-Python (Join-Path $Common 'inspect_inputs.py') @('--root',$InputRoot,'--output',(Join-Path $OutputRoot 'input_manifest.json'))
}
if($Action -eq 'segment'){
  if(-not $Config){throw '需要-Config'}
  Run-Python (Join-Path $Common 'segment_preliminary.py') @('--config',$Config)
}
if($Action -eq 'validate'){
  if(-not $InputRoot){throw '需要-InputRoot'}
  if(-not $OutputRoot){
    $inputResolved = (Resolve-Path -LiteralPath $InputRoot).Path
    $parent = Split-Path $inputResolved -Parent
    $leaf = Split-Path $inputResolved -Leaf
    $OutputRoot = Join-Path $parent ($leaf + '_forest_gis_validation')
  }
  # Validation reports are outputs too. Keep them outside the supplied project
  # root so a read-only teacher data directory is never modified by default.
  $safePy = Resolve-PlainPython @()
  Invoke-Native $safePy.Exe $safePy.Prefix (Join-Path $Common 'check_output.py') @('--input',$InputRoot,'--output',$OutputRoot) 'Path safety'
  # validate_project.py 退出码语义：0=无问题，2=发现质量问题（仍会写出 quality_report.json），其他=脚本崩溃。
  # 发现质量问题属“质量判定”而非“崩溃”，不应中断后续拓扑校验；仅对崩溃(exit!=0且!=2)抛错。
  $pyQ = Resolve-PlainPython (Get-RequiredModules $Action)
  & $pyQ.Exe @($pyQ.Prefix) (Join-Path $Common 'validate_project.py') @('--project',$InputRoot,'--report',(Join-Path $OutputRoot 'quality_report.json'))
  $qualExit = $LASTEXITCODE
  if($qualExit -ne 0 -and $qualExit -ne 2){ throw "validate_project.py 执行失败: interpreter=$($pyQ.Exe) script=validate_project.py exit=$qualExit" }
  if($qualExit -eq 2){ Write-Warning "validate_project.py 报告质量检查发现问题（exit=2），详见 quality_report.json" }
  # 拓扑校验：优先显式 GPKG 路径；未提供时只检查 $InputRoot\forest_compartments.gpkg；找不到则明确报错
  if($Gpkg){ $topoGpkg = $Gpkg }
  else { $topoGpkg = Join-Path $InputRoot 'forest_compartments.gpkg' }
  if(-not (Test-Path $topoGpkg)){ throw "未找到 forest_compartments.gpkg，路径: $topoGpkg（可用 -Gpkg 显式指定）" }
  $pyT = Resolve-PlainPython (Get-RequiredModules $Action)
  & $pyT.Exe @($pyT.Prefix) (Join-Path $Common 'validate_topology.py') @('--gpkg',$topoGpkg,'--layer','xiaoban_preliminary','--report',(Join-Path $OutputRoot 'topology_report.json'))
  $topoExit = $LASTEXITCODE
  if($topoExit -ne 0 -and $topoExit -ne 2){ throw "validate_topology.py 执行失败: interpreter=$($pyT.Exe) script=validate_topology.py exit=$topoExit" }
  if($topoExit -eq 2){ Write-Warning "validate_topology.py 报告拓扑检查发现问题（exit=2），详见 topology_report.json" }
  if($qualExit -eq 2 -or $topoExit -eq 2){ exit 2 }
}
if($Action -eq 'package'){
  if(-not $InputRoot -or -not $ZipOutput){throw '需要-InputRoot和-ZipOutput'}
  Run-Python (Join-Path $Common 'package_project.py') @('--project',$InputRoot,'--output',$ZipOutput,'--mode','delivery')
}
if($Action -eq 'build-data'){
  if(-not $Config){throw '需要-Config'}
  Run-ArcPy (Join-Path $Pro 'prepare_project_data.py') @('--config',$Config)
}
if($Action -eq 'prepare-practice'){
  if(-not $InputRoot){throw '需要-InputRoot'}
  if(-not $OutputRoot){throw '需要-OutputRoot'}
  $workflowArgs = @('--input-root',$InputRoot,'--output-root',$OutputRoot,'--mode',$Mode)
  if($DryRun){ $workflowArgs += '--dry-run' }
  else {
    $propy = Resolve-Propy
    $workflowArgs += @('--propy-bat',$propy)
  }
  if($Config){ $workflowArgs += @('--config',$Config) }
  if($ExpectedCompartmentCount -ne $null){ $workflowArgs += @('--expected-compartment-count',[string]$ExpectedCompartmentCount) }
  if($WorkingCrs){ $workflowArgs += @('--working-crs',$WorkingCrs) }
  if($DemZUnit){ $workflowArgs += @('--dem-z-unit',$DemZUnit) }
  if($ZFactor -ne $null){ $workflowArgs += @('--z-factor',[string]$ZFactor) }
  if($DemCellSize -ne $null){ $workflowArgs += @('--dem-cell-size',[string]$DemCellSize) }
  if($ZipOutput){ $workflowArgs += @('--zip-output',$ZipOutput) }
  if($Resume){ $workflowArgs += '--resume' }
  if($Revalidate){ $workflowArgs += '--revalidate' }
  if($SkipPackage){ $workflowArgs += '--skip-package' }
  if($ApproveCandidates){ $workflowArgs += '--approve-candidates' }
  $pyW = Resolve-PlainPython (Get-RequiredModules $Action)
  & $pyW.Exe @($pyW.Prefix) (Join-Path $Common 'prepare_practice.py') @workflowArgs
  $workflowExit = $LASTEXITCODE
  if($workflowExit -eq 2){ exit 2 }
  if($workflowExit -ne 0){ exit $workflowExit }
}
if($Action -eq 'project'){
  # EXPERIMENTAL_FEATURE_DISABLED in v1.1.0
  # APRX auto-creation triggered reproducible c0000005 native access violations
  # in ArcGIS Pro 3.5.3 via python.exe (propy.bat). See docs/diagnostics/aprx_native_crash/
  $manualGuide = Join-Path $Root 'docs\ArcGISPro_手动创建小班项目.md'
  Write-Host ''
  Write-Host '=============================================='
  Write-Host ' APRX 自动创建功能已禁用'
  Write-Host ' (EXPERIMENTAL_FEATURE_DISABLED)'
  Write-Host '=============================================='
  Write-Host ''
  Write-Host '当前版本的 ArcGIS Pro 3.5.3 测试环境中，'
  Write-Host '该流程发生过可重复的 c0000005 原生访问违例。'
  Write-Host ''
  Write-Host 'ProjectData.gdb 和栅格成果已可正常使用。'
  Write-Host '请按照以下文档在 ArcGIS Pro 中手动创建项目：'
  Write-Host ''
  Write-Host "  $manualGuide"
  Write-Host ''
  Write-Host '退出码 4 = EXPERIMENTAL_FEATURE_DISABLED'
  Write-Host ''
  exit 4
}
