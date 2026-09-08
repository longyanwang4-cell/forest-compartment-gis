---
name: forest-compartment-gis
description: 检查森林小班区划数据、生成待人工核查的候选小班，并构建或校验 ArcGIS Pro 成果数据。适用于森林经理学实习、小班区划或 ArcGIS Pro 小班工程；不用于自动定版边界、树种或蓄积量。
metadata:
  version: "1.5.1-codex"
---

# 森林小班 GIS Skill

这是适用于 Codex 的 Windows 本地 GIS 工作流。统一入口为 `Tools\forest-gis.ps1`；所有路径均以本 `SKILL.md` 所在目录为 Skill 根目录。

## 适用范围

用于老师提供森林经理学实习数据后，帮助 GIS 负责人：

1. 检查环境与输入数据；
2. 识别主影像、Bound 边界、DEM 和已有小班；
3. 在没有现成小班时生成仅供人工核查的候选小班；
4. 构建 ArcGIS Pro 可编辑数据；
5. 检查字段、坐标系、覆盖关系和拓扑。

不自动决定最终小班边界，不判断树种、蓄积量，不替代外业踏查和教师验收。

## 执行纪律

- 仅在 Windows 本机、能够访问用户文件并执行 PowerShell 时运行。
- 首次运行先执行 `doctor`。
- 所有写入只允许进入用户明确指定的新输出目录；不得写入或覆盖老师原始数据目录。
- `segment`、`build-data`、`prepare-practice`、`package` 属于会创建成果的动作。除非用户已明确说“执行/开始/运行”，否则先展示将执行的命令、输入目录和输出目录，并取得确认。
- 发现多个关键候选输入、未知坐标系、未知 DEM 单位或验证问题时停止，不猜测。
- 候选小班必须标明“待人工核查”。
- 不调用网络，不上传输入数据。

先用 `inspect` 生成清单并向用户报告已识别的影像、边界、DEM 和已有小班。存在多个关键候选、未知坐标系或未知 DEM 单位时，要求用户明确选择；不要猜测。只有用户明确要求执行产出类操作且给出了独立输出目录时，才运行 `segment`、`build-data`、`prepare-practice` 或 `package`。

## 调用方式

推荐目标级命令：

```powershell
powershell -NoProfile -File "<Skill根目录>\Tools\forest-gis.ps1" `
  -Action prepare-practice `
  -InputRoot "D:\To_Stu" `
  -OutputRoot "D:\Forest_Project" `
  -Mode standard
```

只检查环境：

```powershell
powershell -NoProfile -File "<Skill根目录>\Tools\forest-gis.ps1" -Action doctor
```

查看工具清单：

```powershell
powershell -NoProfile -File "<Skill根目录>\Tools\forest-gis.ps1" -Action tools
```

## 退出码

- `0`：成功；
- `1`：一般错误；
- `2`：成果已生成，但存在验证问题或需要人工核查；
- `3`：输入错误或存在歧义；
- `4`：实验性功能禁用；
- `5`：环境错误；
- `6`：脚本错误。

不得把 `exit 2` 描述成“全部完成”。读取输出目录中的 `03_Reports` 和 `00_Workflow/workflow_state.json` 后再向用户汇报。

## 关键文档

- `references/safety.md`
- `references/workflow.md`
- `references/troubleshooting.md`
- `registry/tool_registry.json`
