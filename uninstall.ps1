param(
    [string]$ProjectRoot,
    [string]$SkillsRoot,
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
$SkillName = 'forest-compartment-gis'
$TargetRoot = if ($SkillsRoot) { $SkillsRoot } elseif ($ProjectRoot) { Join-Path $ProjectRoot '.agents\skills' } elseif ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $env:USERPROFILE '.codex\skills' }
$Target = Join-Path ([System.IO.Path]::GetFullPath($TargetRoot)) $SkillName
. (Join-Path $PSScriptRoot 'Tools\install-path-safety.ps1')
Assert-NoReparsePath $Target
$Marker = Join-Path $Target '.forest-gis-skill.json'
if (-not (Test-Path -LiteralPath $Target)) { Write-Host '未安装，无需卸载'; exit 0 }
if (-not (Test-Path -LiteralPath $Marker) -and -not $Force) {
    throw "目标缺少管理标记，拒绝删除。确认后可使用 -Force: $Target"
}
if (Test-Path -LiteralPath $Marker) {
    try {
        $m = Get-Content -LiteralPath $Marker -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($m.skill_name -ne $SkillName -and -not $Force) { throw '管理标记不属于本Skill，拒绝删除' }
    } catch { if (-not $Force) { throw } }
}
$Backup = $Target + '.uninstalled.' + [guid]::NewGuid().ToString('N')
Move-Item -LiteralPath $Target -Destination $Backup
Write-Host "Recoverable backup: $Backup"
Write-Host "已卸载: $Target"
