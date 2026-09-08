param(
    [string]$ProjectRoot,
    [string]$SkillsRoot,
    [switch]$ForceReplaceUnmanaged
)
$ErrorActionPreference = 'Stop'
$SkillName = 'forest-compartment-gis'
$Version = '1.5.1-codex'
$Platform = 'codex'
$Source = [System.IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))
$SourcePrefix = $Source.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
$PackageManifest = Join-Path $Source 'PACKAGE_SHA256SUMS.txt'
if (-not (Test-Path -LiteralPath $PackageManifest -PathType Leaf)) { throw '安装包缺少PACKAGE_SHA256SUMS.txt，拒绝安装' }

# 不允许安装包目录通过junction/symlink重定向，也不安装清单之外的附加文件。
foreach ($item in Get-ChildItem -LiteralPath $Source -Force -Recurse) {
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "安装包包含符号链接或重解析点，拒绝安装: $($item.FullName)"
    }
}

$ManifestEntries = New-Object System.Collections.Generic.List[object]
$Seen = @{}
foreach ($line in Get-Content -LiteralPath $PackageManifest -Encoding UTF8) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    $parts = $line -split '  ', 2
    if ($parts.Count -ne 2) { throw "无效的包清单行: $line" }
    $expected = $parts[0].Trim().ToLowerInvariant()
    if ($expected -notmatch '^[0-9a-f]{64}$') { throw "无效SHA256: $line" }
    $relative = $parts[1].Trim().Replace('/', [IO.Path]::DirectorySeparatorChar)
    if ([string]::IsNullOrWhiteSpace($relative) -or [IO.Path]::IsPathRooted($relative) -or $relative.Contains(':')) {
        throw "包清单包含不安全路径: $relative"
    }
    $segments = $relative.Split([IO.Path]::DirectorySeparatorChar)
    if ($segments -contains '..' -or $segments -contains '') { throw "包清单包含不安全路径: $relative" }
    $key = $relative.ToLowerInvariant()
    if ($Seen.ContainsKey($key)) { throw "包清单包含重复/大小写冲突路径: $relative" }
    $Seen[$key] = $true
    $file = [IO.Path]::GetFullPath((Join-Path $Source $relative))
    if (-not $file.StartsWith($SourcePrefix, [StringComparison]::OrdinalIgnoreCase)) { throw "包文件逃逸安装目录: $relative" }
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "包文件缺失: $relative" }
    $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { throw "包文件校验失败: $relative" }
    $ManifestEntries.Add([pscustomobject]@{ Relative=$relative; Source=$file }) | Out-Null
}
if ($ManifestEntries.Count -eq 0) { throw '包清单为空，拒绝安装' }

# 清单必须精确覆盖包内普通文件；额外注入的文件也会导致安装失败。
foreach ($fileItem in Get-ChildItem -LiteralPath $Source -Force -Recurse -File) {
    if ($fileItem.FullName -eq $PackageManifest) { continue }
    $relative = $fileItem.FullName.Substring($SourcePrefix.Length).Replace('/', [IO.Path]::DirectorySeparatorChar)
    if (-not $Seen.ContainsKey($relative.ToLowerInvariant())) {
        throw "安装包包含未登记文件，拒绝安装: $relative"
    }
}

$TargetRoot = if ($SkillsRoot) { $SkillsRoot } elseif ($ProjectRoot) { Join-Path $ProjectRoot '.agents\skills' } elseif ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $env:USERPROFILE '.codex\skills' }
if ([string]::IsNullOrWhiteSpace($TargetRoot)) { throw '无法确定Skill安装目录' }
$TargetRoot = [System.IO.Path]::GetFullPath($TargetRoot)
$Target = Join-Path $TargetRoot $SkillName
. (Join-Path $Source 'Tools\install-path-safety.ps1')
Assert-NoReparsePath $Source
Assert-NoReparsePath $Target
if ($Target -eq $Source -or $Source.StartsWith($Target.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or $Target.StartsWith($SourcePrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Source and target must be disjoint' }
$Marker = Join-Path $Target '.forest-gis-skill.json'
New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null

if (Test-Path -LiteralPath $Target) {
    $Managed = $false
    if (Test-Path -LiteralPath $Marker) {
        try {
            $m = Get-Content -LiteralPath $Marker -Raw -Encoding UTF8 | ConvertFrom-Json
            $Managed = ($m.skill_name -eq $SkillName)
        } catch { $Managed = $false }
    }
    if (-not $Managed -and -not $ForceReplaceUnmanaged) {
        throw "目标目录已存在且不是本生成器管理的Skill，拒绝覆盖: $Target"
    }
}

$Stage = Join-Path $TargetRoot ('.' + $SkillName + '.stage.' + [guid]::NewGuid().ToString('N'))
$Backup = $null
try {
    New-Item -ItemType Directory -Force -Path $Stage | Out-Null
    foreach ($entry in $ManifestEntries) {
        $destination = Join-Path $Stage $entry.Relative
        $parent = Split-Path -Parent $destination
        if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
        Copy-Item -LiteralPath $entry.Source -Destination $destination -Force
    }
    Copy-Item -LiteralPath $PackageManifest -Destination (Join-Path $Stage 'PACKAGE_SHA256SUMS.txt') -Force
    if (Test-Path -LiteralPath $Target) {
        $Backup = $Target + '.backup.' + [guid]::NewGuid().ToString('N')
        Move-Item -LiteralPath $Target -Destination $Backup
    }
    Move-Item -LiteralPath $Stage -Destination $Target
    Write-Host "已安装: $Target"
    if ($Backup) { Write-Host "旧版本备份: $Backup" }
} catch {
    if (Test-Path -LiteralPath $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue }
    if ($Backup -and (Test-Path -LiteralPath $Backup) -and -not (Test-Path -LiteralPath $Target)) {
        Move-Item -LiteralPath $Backup -Destination $Target -ErrorAction SilentlyContinue
    }
    throw
}
