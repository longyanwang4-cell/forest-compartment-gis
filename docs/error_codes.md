# 统一退出码

| 退出码 | 名称 | 含义 |
|---:|---|---|
| 0 | SUCCESS | 命令成功 |
| 1 | GENERAL_ERROR | 未进一步分类的一般错误 |
| 2 | VALIDATION_ISSUES | 校验完成但发现质量问题，不等同脚本崩溃 |
| 3 | INPUT_ERROR | 请求、配置或必填路径不正确 |
| 4 | EXPERIMENTAL_FEATURE_DISABLED | 实验功能已禁用；当前用于 project |
| 5 | ENVIRONMENT_ERROR | Python、依赖、ArcPy 或 propy 环境不可用 |
| 6 | SCRIPT_ERROR | 子脚本执行异常或非预期退出 |

## 兼容说明

v1.1.0 的 PowerShell 入口原有行为保持不变。v1.2.0-dev 控制层使用以上完整枚举；平台适配器应保留原始退出码，不得把 exit 2 或 exit 4 伪装成 SUCCESS。
