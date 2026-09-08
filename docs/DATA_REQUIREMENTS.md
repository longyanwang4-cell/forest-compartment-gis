# 数据准备说明

本 Skill 处理的是森林小班区划候选成果。真实老师数据、科研数据和影像只应在本机使用，不要上传到公共 GitHub 仓库。

## 最低必需数据

### 1. 主影像

- 推荐格式：GeoTIFF（`.tif`/`.tiff`）
- 内容：研究区遥感影像或正射影像
- 必须有有效的水平坐标系和地理参考信息
- 多个影像候选时必须在配置中明确指定，不能依文件名猜测

### 2. 工作边界

- 推荐格式：Shapefile（`.shp`）或 GeoPackage
- 几何类型：面
- 内容：本次小班区划的工作范围
- 必须有有效坐标系；Shapefile 应同时提供 `.shp`、`.shx`、`.dbf`、`.prj`

### 3. 坐标系信息

请为影像、边界和 DEM 分别提供：坐标系名称、EPSG/WKID（如有）、水平单位，以及 DEM 的高程单位。优先提供原始 `.prj` 文件和 ArcGIS Pro 的 Spatial Reference 信息，不要凭猜测填写 EPSG。

## 推荐数据

- DEM：GeoTIFF；注明水平坐标系和高程单位（米/英尺等）
- 已有小班候选：`xiaoban_preliminary.shp` 或 GeoPackage 图层
- 外业轨迹点、轨迹线、照片点
- 控制点、标准样地和其他质量检查图层

DEM 参与坡度、地形等处理时，配置必须明确 `dem_z_unit` 和必要的 `z_factor`。

## 推荐输入目录

```text
Input/
├── imagery.tif
├── Bound.shp
├── Bound.shx
├── Bound.dbf
├── Bound.prj
└── DEM/
    └── dem.tif
```

输入目录必须与输出目录分开，原始数据视为只读。Skill 会检查路径安全和输入/输出隔离，但不会替代数据质量或权属审查。

## 坐标系填写示例

```text
主影像：imagery.tif
坐标系：<ArcGIS Pro 中显示的完整名称>
EPSG/WKID：<编号，如有>
水平单位：米/度

工作边界：Bound.shp
坐标系：<完整名称>
EPSG/WKID：<编号，如有>
水平单位：米/度

DEM：dem.tif
水平坐标系：<完整名称>
EPSG/WKID：<编号，如有>
水平单位：米/度
高程单位：米/英尺/其他（必须注明）
```

影像、边界和 DEM 应一致，或明确说明如何转换到同一个目标坐标系。发现坐标系未知、数据单位未知或同类数据存在多个候选时，工作流应停止并要求人工确认。

## ArcGIS Pro 项目目录

使用 ArcGIS Pro 00 工具时，应选择包含 `ProjectData.gdb` 的上级目录，而不是 `.gdb` 本身：

```text
ForestGIS_Project/
├── ProjectData.gdb/
└── Data/
    ├── imagery_full.tif
    ├── imagery_clip.tif
    └── DEM/
        ├── dem_full.tif
        └── dem_clip.tif
```

## 检查方式

在 ArcGIS Pro 中右键图层 → Properties → Source → Spatial Reference，记录 Name、WKID/EPSG 和单位。处理前后不要移动、覆盖、重命名或上传老师提供的原始文件。
