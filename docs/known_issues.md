# Known Issues

## v1.2.0-dev

### Kimi Code / WorkBuddy / QoderWork CN 平台复测

**状态**：PLATFORM_RETEST_REQUIRED

Kimi Code、WorkBuddy、QoderWork CN 薄适配器和统一计划已经实现并通过纯 Python 契约测试，但本开发包尚未在这些平台中完成安装、权限和实际命令入口复测。因此不得标记为平台正式验证完成。

### APRX 自动创建：原生访问违例

**状态**：EXPERIMENTAL_DISABLED

**已观察环境**：ArcGIS Pro 3.5.3，python.exe via propy.bat。

项目自动创建测试在 `arcpy._mp.setDefinition()` 处发生 c0000005 原生访问违例。该结论只适用于当前测试环境，不应推广为所有 ArcGIS Pro 3.5.3 安装的通用缺陷。

保护措施：

- `project` 动作返回 exit 4；
- `create_or_update_project.py` 在导入 ArcPy 前无条件返回 exit 4；
- 默认不会创建 APRX；
- 使用 `docs\ArcGISPro_手动创建小班项目.md`。

影响：

- 不影响 `ProjectData.gdb`；
- 不影响分割、拓扑、地形统计和验证；
- 不修改原始输入。

证据位于 `docs/diagnostics/aprx_native_crash/`。

### ArcMap 10.8

**状态**：NOT_COMPLETED

目前只有占位说明，未提供正式 Python 2.7 / arcpy.mapping 工作流。

### QGIS

**状态**：NOT_COMPLETED

目前没有可发布的 PyQGIS、qgis_process 或 QGZ 自动化后端。

## v1.1.0

v1.1.0 是已冻结的数据流程稳定基线。v1.2.0-dev 不重写其 GIS 算法。

## v1.3.0-dev 补充

- `prepare-practice` 已通过伪执行器单元测试，但尚未在 Windows PowerShell 5.1 + ArcGIS Pro 3.5 上完整实机复测；
- APRX 自动创建继续禁用；
- 输入中同类数据有多个候选时，工作流会停止并要求在配置中明确路径；
- GeoPackage 含多个图层时，当前输入检查只读取默认图层，建议优先明确提供小班 Shapefile，或先导出单一小班图层；
- exit 2 表示工作流已完成检查但暂停人工复核，不是程序崩溃。

## v1.3.1-beta 补充

- 新增最终 GDB ArcPy 深度验证，但该脚本尚未在真实 ArcGIS Pro 3.5 数据上运行；
- `Check Geometry` 只检查并报告，不自动修复；
- 默认重叠/缺口容差适用于当前教学候选成果，老师有不同要求时应修改 `validation` 配置；
- `-Resume` 会在暂停状态下重跑验证；`-Revalidate` 会无条件清除验证步骤完成状态并重跑；
- 默认交付 ZIP 不包含 `01_Segmentation` 中间文件；需要完整调试包时可单独运行 `package_project.py --mode full`；
- 当前仍未提供 ArcMap 10.8 和 QGIS 正式后端。

## v1.4.0-beta 补充

- `strict` 模式的完整输入哈希可能对大型影像耗时较长；这是明确选择的审计强度，不是卡死。
- 双击启动器依赖 Windows PowerShell 和 Windows Forms；命令行入口仍是权威入口。
- `Field_Kit` 是中性表单模板，不是完整 QField、Field Maps 或 Open Foris 项目。
- 内置 benchmark 只覆盖契约与适配器，不代表真实空间分析成功率。
- QGIS、ArcMap 10.8 后端仍未实现，不应因存在目录或适配器而宣称支持。
