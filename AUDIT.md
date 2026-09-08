# Codex 兼容性与对抗式审查

审查日期：2026-09-08。结论：原包不能作为完整可靠的 Codex 发布包直接使用；修复后的 1.5.1-codex 已通过格式、控制层和隔离安装验证。尚未完成真实 GIS 数据端到端验收。

| 发现 | 修复或处理 |
| --- | --- |
| Claude 平台元数据、安装目标和专属禁用字段 | 改为 Codex 入口，新增 agents/openai.yaml，支持用户级与项目级安装 |
| plan 导入未随包提供的 adapters，参数又不接受 codex | 直接复用已有 CommandRequest 契约，CLI 与 PowerShell 平台选项统一 |
| benchmark 默认场景文件缺失 | 补齐三个基础契约场景；明确不是 GIS 性能测试 |
| inspect 安全校验前创建目录 | 交由 Python 先校验，再创建报告父目录 |
| validate 默认写入输入目录 | 默认改为同级报告目录，入口在任何报告写入前校验隔离与重解析路径 |
| 深入检查抛异常只记 warning，可能返回成功 | 改为 error 并返回质量问题退出码 |
| 实际使用 Fiona 但依赖清单遗漏 | 补入依赖，并修正 inspect 依赖探测 |
| 两个示例将输出嵌套在老师数据内 | 改为同级目录 |
| package 入口默认 full 模式可能暴露本地记录 | PowerShell 交付入口显式使用 delivery 模式 |
| 安装目标父级链接未检查，卸载直接递归删除 | 增加安装路径重解析检查；卸载改名保留副本 |
| 缓存、历史备份和失效 SHA 清单影响安装 | 发布构建排除缓存与备份，重新生成 SHA 清单；原文件保留 |
| Windows PowerShell 5.1 中文源码编码问题 | 发布构建统一 PS1 为 UTF-8 BOM 与 CRLF，全部通过解析 |
| README 声称包含实际缺失的多平台生成器和测试 | 重写实际安装、构建、调用说明与安全边界 |

## 已执行验证

- Codex skill-creator quick_validate：通过。
- 五项独立回归检查：通过，包括 Codex 计划、禁用 APRX、嵌套输出拒绝且不落盘、空目录检查。
- 三项基础契约 benchmark：3/3 通过。
- 所有发布版 PowerShell 文件语法解析：0 错误。
- 发布目录 SHA 清单安装校验及安装到工作区 `.test-output/skills`：通过。
- 发布版 plan CLI：成功生成 Codex 计划。
- doctor：检测到本机 ArcGIS Pro，但 ArcPy 导入未通过，ready=false。

本机执行策略原本禁用 PowerShell 脚本；经单次进程权限放行完成安装实测，未修改系统执行策略。其他电脑也可能需要按当地管理策略放行脚本。

## 验证边界与剩余风险

没有提供可用于验收的真实输入 GIS 数据，本机 ArcPy readiness 也未通过，因此不能宣称分割、GDB 构建、地形统计和真实小班拓扑已端到端验证。低层脚本并非统一隔离的服务接口：Codex 应从 SKILL.md 指定入口使用，并检查输入和输出配置。GIS 驱动、复杂几何处理、断点恢复、打包二进制隐私和 TOCTOU 竞态没有穷尽验证。

旧缓存和两份工具箱历史备份仍保存在源文件夹，被 Git 忽略并排除于发布 ZIP。隔离安装测试结果保存在 `.test-output`；没有更改用户现有 Codex Skill 安装，也没有上传 GitHub。

格式依据：本机 skill-creator 规范及 [OpenAI 官方 Skill 文档](https://learn.chatgpt.com/docs/build-skills)。删除其他平台专属字段不等于原字段必然导致 Codex 拒绝加载；此次修复采用最小兼容元数据并通过本机验证器确认。
