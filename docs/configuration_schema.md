# 统一请求与配置格式

## 1. 请求格式

统一请求用于描述“要执行哪个动作以及入口参数”。

```json
{
  "schema_version": "1.0",
  "command": "validate",
  "input_root": "D:/ForestGIS_Project_Data",
  "output_root": "D:/ForestGIS_Project_Data/reports",
  "gpkg": "D:/ForestGIS_Project_Data/forest_compartments.gpkg",
  "platform": "universal",
  "metadata": {
    "request_id": "example-001"
  }
}
```

### 命令

- `doctor`
- `inspect`
- `segment`
- `build-data`
- `validate`
- `package`
- `project`（禁用）
- `prepare-practice`

### 必填规则

| 命令 | 必填字段 |
|---|---|
| doctor | 无 |
| inspect | input_root |
| segment | config |
| build-data | config |
| validate | input_root |
| package | input_root、zip_output |
| project | 无，但固定返回 exit 4 |
| prepare-practice | input_root、output_root；propy 由 PowerShell 入口解析 |


## 2. 统一处理配置字段

统一处理配置至少提供以下稳定字段；旧版配置会由 `normalize_processing_config()` 自动提取并补齐：

| 字段 | 含义 |
|---|---|
| input_root | 输入根目录，可为空 |
| output_root | 输出目录 |
| imagery | 影像路径 |
| dem | DEM路径 |
| boundary | 作业边界路径 |
| compartments | 已有/候选小班路径 |
| backend | `common-python` 或 `arcgis-pro` |
| python_environment | 普通Python与propy配置 |
| safety | 原始数据保护与覆盖策略 |
| reports | 报告输出配置 |
| payload | 保留给v1.1.0业务脚本的原始配置 |

完整示例见 `templates/unified-processing-config.example.json`。

## 3. 处理配置兼容

v1.2.0-dev 不强制重写已有业务配置。以下 v1.1.0 配置仍可直接使用：

- `templates/segmentation-config.example.json`
- `templates/arcgis-pro-build-config.example.json`

`forestgis_core.config.normalize_processing_config()` 可以为旧配置增加统一外壳，同时原样保留 `payload`，因此旧脚本仍能读取同样字段和得到同样计算结果。

统一外壳示例：

```json
{
  "schema_version": "1.0",
  "command": "segment",
  "backend": "common-python",
  "payload": {
    "input": {},
    "output_dir": "D:/out",
    "segmentation": {}
  },
  "safety": {
    "protect_original_inputs": true,
    "allow_existing_output": false
  },
  "compatibility": {
    "source_format": "v1.1.0-segment",
    "legacy_payload_preserved": true
  }
}
```

## 4. plan 输出

计划只说明将调用哪些脚本、运行时和参数，不实际执行：

```json
{
  "request": {},
  "plan": {
    "command": "build-data",
    "steps": [
      {
        "name": "prepare-project-data",
        "runtime": "arcgis-propy",
        "script": ".../prepare_project_data.py",
        "arguments": ["--config", "D:/build.json"]
      }
    ],
    "disabled": false
  }
}
```

## 5. 规划动作退出语义

`plan_command.py` 成功解析并写出计划时返回 exit 0。计划目标命令的预期退出码单独保存在 `plan.expected_exit_code`；因此为已禁用的 `project` 生成计划时，规划器仍返回0，而计划中记录4。

## 6. v1.3.1 `prepare-practice` 工作流配置

```json
{
  "input_root": "D:/To_Stu",
  "output_root": "D:/Forest_Practice_Project",
  "input": {
    "imagery": null,
    "boundary": null,
    "dem": null,
    "compartments": null
  },
  "expected_compartment_count": 20,
  "working_crs": "EPSG:32652",
  "terrain": {
    "dem_z_unit": "METER",
    "z_factor": 1.0,
    "dem_cell_size": null
  },
  "validation": {
    "overlap_tolerance_m2": 1.0,
    "gap_tolerance_m2": 5.0,
    "outside_tolerance_m2": 1.0,
    "min_coverage_ratio": 0.999,
    "require_projected_crs": true,
    "require_meter_unit": true
  },
  "package": {"enabled": true}
}
```

说明：

- `expected_compartment_count` 仅在未提供已有小班时使用，必须来自本次配置或用户输入；
- 已有小班时，工作流从输入要素数量读取预期数量；
- `working_crs` 只作用于本次项目；
- 检测到 DEM 时，`dem_z_unit` 和 `z_factor` 必须显式提供；
- 输入目录中同一类型存在多个候选时，使用 `input` 节点明确指定路径。


### 验证恢复参数

- `-Resume`：继续已有工作流；若上次状态为 `PAUSED_FOR_REVIEW`，自动重新执行全部验证步骤；
- `-Revalidate`：在已有工作流上强制重新执行 `validate-gdb`、`validate-project` 和 `validate-topology`；
- exit 2 的验证步骤保存在 `review_steps`，不会写入 `completed_steps`。

### validation 字段

| 字段 | 含义 | 默认值 |
|---|---|---:|
| overlap_tolerance_m2 | 允许的小班总重叠面积 | 1.0 |
| gap_tolerance_m2 | 允许的边界内缺口面积 | 5.0 |
| outside_tolerance_m2 | 允许的小班越界面积 | 1.0 |
| min_coverage_ratio | 最低边界覆盖率 | 0.999 |
| require_projected_crs | 最终小班必须使用投影坐标系 | true |
| require_meter_unit | 最终小班线性单位必须为米 | true |

## 7. v1.4.0 新增控制字段

```json
{
  "execution_mode": "standard",
  "human_oversight": {
    "review_candidate_before_build": false
  },
  "reporting": {
    "html_summary": true,
    "field_kit": true
  },
  "provenance": {
    "hash_mode": "sampled"
  },
  "candidate_review_approved": false
}
```

- `execution_mode`: `fast` / `standard` / `strict`。
- `review_candidate_before_build`: 自动生成候选小班后是否在建库前暂停。
- `hash_mode`: `quick` / `sampled` / `full`；大型影像使用 `full` 会显著增加耗时。
- `candidate_review_approved`: 恢复严格模式时的人工审批标记；不参与业务配置指纹，可从 `false` 改为 `true` 后 `-Resume`。
