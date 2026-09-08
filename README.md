# 森林小班 GIS · Codex Skill

面向 Windows 的森林小班区划助手，版本 `1.5.1-codex`。

## 下载与安装

下载本仓库中的 [forest-compartment-gis-codex.zip](forest-compartment-gis-codex.zip)，解压后进入 `forest-compartment-gis` 文件夹，在 PowerShell 执行：

```powershell
powershell -NoProfile -File .\install.ps1
```

默认安装到用户的 Codex skills 目录。若本机策略禁止脚本运行，请按本机管理策略放行。重开 Codex 任务后输入：

```text
使用 $forest-compartment-gis 检查我的森林小班数据。
输入目录：D:\To_Stu
报告目录：D:\Forest_Check
先运行 doctor，再检查输入。
```

请替换实际路径，报告和成果目录应独立于老师原始数据目录。

## ArcGIS Pro 工具箱

完整源码及工具箱均在 ZIP 内，保留原目录结构。工具箱位于：

`scripts/arcgis_pro/ForestCompartmentPro35.pyt`

在 ArcGIS Pro 的目录窗格中右键“工具箱”→“添加工具箱”，选择该文件。功能包括项目初始化、轨迹导入、面积与中心点更新、成果检查。

## 当前验证范围

已通过 Skill 格式检查、五项控制层回归检查、三项契约测试、PowerShell 语法检查及隔离安装。实际 ArcGIS Pro 工具箱加载和真实 GIS 全流程尚未完成验收；本次环境中 ArcPy 导入检查未通过。候选小班必须人工核查。

普通处理需要 Python 3.10+ 及包内 requirements-segmentation.txt 中的 GIS 依赖，GDB 构建需要已授权的 ArcGIS Pro。自动 APRX 创建入口当前禁用。

详见 [审查报告](AUDIT.md)。尚未指定开源许可证。
