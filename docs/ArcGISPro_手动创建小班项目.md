# ArcGIS Pro 手动创建森林小班项目

## 1. 准备数据

本次示例数据目录：

```
D:\ForestGIS_Development\build_data_test_rep
```

正式使用时可替换为教师提供的数据成果目录。

必须存在：
- `ProjectData.gdb`
- `Data\imagery_full.tif`
- `Data\imagery_clip.tif`
- `Data\DEM\dem_clip.tif`

## 2. 新建项目

1. 启动 ArcGIS Pro
2. 选择"地图"模板
3. 项目名称建议为：`ForestCompartments`
4. 选择自己的项目保存目录
5. 点击"确定"
6. 不要修改教师提供的原始数据目录

## 3. 添加文件夹连接

1. 在"目录"窗格中右键"文件夹"
2. 选择"添加文件夹连接"
3. 连接到数据成果目录
4. 展开 `ProjectData.gdb` 和 `Data` 文件夹

## 4. 创建分组图层

在"内容"窗格中创建以下5个分组，并从上到下排列：

```
05 样地
04 外业核对
03 两步路与导航
02 小班区划
01 影像与地形
```

允许保留 ArcGIS Pro 自动添加的地形底图，但地形底图应位于所有本地业务图层下方。

## 5. 添加图层并排序

最终内容列表从上到下应为：

```
05 样地
  Standard_Plot_Polygons
  Control_Plot_Centers

04 外业核对
  Photo_Points
  Boundary_Adjustment_Lines
  Field_Check_Points

03 两步路与导航
  TwoSteps_Track_Points
  TwoSteps_Track_Lines

02 小班区划
  Xiaoban_Centers
  Xiaoban_Preliminary
  Work_Boundary

01 影像与地形
  dem_clip.tif
  imagery_full.tif
  imagery_clip.tif

地形底图（可选）
```

## 6. 初始可见性

**开启（可见）：**

- Standard_Plot_Polygons
- Control_Plot_Centers
- Photo_Points
- Boundary_Adjustment_Lines
- Field_Check_Points
- TwoSteps_Track_Lines
- Xiaoban_Preliminary
- Work_Boundary
- imagery_clip.tif
- 地形底图（可选）

**关闭（不可见）：**

- TwoSteps_Track_Points
- Xiaoban_Centers
- dem_clip.tif
- imagery_full.tif

## 7. 设置小班符号

Xiaoban_Preliminary：
- 填充：无颜色
- 轮廓：黄色
- 轮廓宽度：约 1.5 pt

## 8. 设置作业边界符号

Work_Boundary：
- 填充：无颜色
- 轮廓：红色
- 轮廓宽度：约 2 pt

## 9. 设置小班标注

对 Xiaoban_Preliminary：
- 开启标注
- 标注字段：`XB_ID`
- 字体颜色：黑色
- 字号：约 9 pt
- 光晕颜色：白色
- 光晕宽度：约 1 pt

## 10. 设置地图范围

1. 右键 Work_Boundary
2. 选择"缩放至图层"
3. 适当向外缩小一级
4. 保留边界周围少量空间

## 11. 保存与检查

1. 保存项目
2. 关闭 ArcGIS Pro
3. 重新打开项目
4. 检查是否存在红色感叹号
5. 确认所有本地业务图层均能显示
6. 无网络时，在线底图可能无法显示，但本地图层不应受影响

## 12. 禁止操作

学生不得：

- 修改 `XB_ID`
- 修改 `STATUS`
- 拆分小班
- 合并小班
- 删除小班
- 修改小班编号
- 修改 `ELEV_M`
- 修改 `SLOPE_DEG`
- 修改 `REMARK`
- 修改或覆盖教师提供的原始数据
- 将 `ProjectData.gdb` 移出成果目录后继续使用旧项目路径

说明：

`STATUS` 应保持为：

```
PRELIMINARY
```
