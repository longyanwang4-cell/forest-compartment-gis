# 常见故障

## ArcGIS Pro能打开但检测不到

运行 `Tools/配置ArcGISPro路径.ps1`，或设置：

```text
ARCGIS_PRO_ROOT=<安装根目录>
ARCGIS_PROPY=<根目录>\bin\Python\scripts\propy.bat
ARCGIS_PRO_EXE=<根目录>\bin\ArcGISPro.exe
```

## GDB被锁定

关闭正在使用该GDB的ArcGIS Pro、ArcMap或资源管理器预览，再重试。

## 分割依赖缺失

经用户同意后运行`Tools/setup_segmentation_env.ps1`。不要把现代包安装到ArcMap 10.8的Python 2.7环境。

## 标注没有白色光晕

运行工具箱中的“恢复推荐符号和标注”；若具体补丁版本CIM接口不同，在ArcGIS Pro中手工设为黑色10pt、白色光晕1.5pt。
