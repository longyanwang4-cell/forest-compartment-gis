# Forest Compartment GIS

森林小班 GIS · Codex Skill

AI-assisted GIS and Codex Skill for forest compartment delineation, geometry inspection, field planning, and ArcGIS Pro workflows.

## 项目简介 / Overview

面向森林小班区划、森林经理学教学和科研工作流辅助。项目运行在 Windows，可由 Codex 调用，也可直接在 ArcGIS Pro 中加载 Python Toolbox。它不会自动替代人工定版、外业踏查、树种判断或蓄积量调查。

## 功能 / Features

- 检查影像、边界、DEM、已有小班和轨迹输入
- 生成标注为“待人工核查”的候选小班
- 检查字段、坐标系、覆盖、几何和拓扑
- 生成外业表单和可复现性记录
- 构建 ArcGIS Pro 可编辑数据
- 提供 ArcGIS Pro Python Toolbox：轨迹导入、面积/中心点更新和成果自检
- 提供 Codex Skill 入口与 `doctor` 环境诊断

## 快速开始 / Quick Start

### 方法 A：Git clone

```powershell
git clone https://github.com/longyanwang4-cell/forest-compartment-gis.git
cd forest-compartment-gis
powershell -NoProfile -File .\install.ps1
```

默认安装到 `$CODEX_HOME/skills`；未设置时使用用户 `.codex\skills`。项目安装可使用 `-ProjectRoot <目录>`，自定义目标可使用 `-SkillsRoot <目录>`。依赖安装见 `requirements-segmentation.txt`，GDB 功能需要已授权的 ArcGIS Pro；ArcPy 不通过 pip 提供。

### 方法 B：GitHub Releases

普通用户可从 GitHub Releases 下载版本对应的 `forest-compartment-gis-codex.zip`，解压后进入包目录运行 `install.ps1`。当前第二阶段尚未创建 Release；源码仓库中的 ZIP 暂作为过渡发布物。

## Codex 使用示例

```text
使用 $forest-compartment-gis 检查我的森林小班数据。
输入目录：D:\ForestProject\Input
报告目录：D:\ForestProject\Output
先运行 doctor，再检查输入。
```

输入目录和输出/报告目录必须分开。候选小班必须经过人工核查。

## ArcGIS Pro

工具箱路径：`scripts/arcgis_pro/ForestCompartmentPro35.pyt`。在 ArcGIS Pro“目录”窗格右键“工具箱”→“添加工具箱”，选择该文件。当前包含项目初始化、两步路轨迹导入、面积/中心点更新和项目成果检查。自动 APRX 创建入口已禁用；请按 `docs/ArcGISPro_手动创建小班项目.md` 操作。

## 项目结构 / Repository Structure

`SKILL.md` 和 `agents/` 定义 Codex Skill；`forestgis_core/` 是核心控制与路径安全代码；`scripts/common/` 是普通 Python 工具；`scripts/arcgis_pro/` 是 ArcGIS Pro 后端和工具箱；`Tools/` 是 PowerShell 入口；`docs/`、`references/`、`templates/` 和 `registry/` 提供文档、示例与工具契约。

## Requirements

基础检查需要 Python 3。候选分割、栅格和矢量处理需要 `requirements-segmentation.txt` 中的 NumPy、SciPy、pandas、Rasterio、Fiona、GeoPandas、Shapely、PyProj、scikit-image 和 scikit-learn。ArcGIS Pro 专属动作需要 ArcPy 和有效的 Esri 安装。第三方依赖许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## Validation Status

已完成 Skill 格式检查、控制层回归、契约测试、PowerShell 语法检查、隔离安装和发布包校验。真实 ArcGIS Pro 工具箱加载、ArcPy readiness 和真实 GIS 数据端到端流程尚未完成验收；本机最近一次 ArcPy 导入检查未通过。详见 [AUDIT.md](AUDIT.md) 与 [OPEN_SOURCE_AUDIT.md](OPEN_SOURCE_AUDIT.md)。

## Safety / Data Handling

原始老师数据应视为只读。脚本检查输入/输出隔离并拒绝链接路径，但不构成完整沙箱。不要把真实 GIS 数据、影像、DEM、轨迹、照片或含本机路径的 provenance 提交到公共仓库。

## License

本项目采用 [MIT License](LICENSE)。第三方运行时依赖遵循各自许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## Citation

If you use this project in academic research, please cite the GitHub repository: **Longyan Wang, forest-compartment-gis**. 当前没有 DOI 或论文引用。
