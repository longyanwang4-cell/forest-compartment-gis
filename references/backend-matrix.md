# GIS 后端状态

| 后端 | 状态 | 当前职责 |
|---|---|---|
| ArcGIS Pro 3.5 | DATA_WORKFLOW_VERIFIED | FileGDB构建、栅格裁剪、高程与坡度统计、Python工具箱 |
| ArcGIS Pro APRX自动创建 | EXPERIMENTAL_DISABLED | 当前测试环境在CIM setDefinition处发生c0000005；改为手动建项目 |
| ArcMap 10.8 | NOT_COMPLETED | 只有占位说明，尚未提供可发布工作流 |
| QGIS | NOT_COMPLETED | 只有占位说明，尚未提供PyQGIS/qgis_process工作流 |

现代分割和通用拓扑算法应继续运行在普通 Python 3 环境，不应安装到 ArcMap 10.8 的 Python 2.7 中。
