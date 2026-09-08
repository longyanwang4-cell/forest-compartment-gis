# -*- coding: utf-8 -*-
"""森林小班区划与踏查工具（ArcGIS Pro 3.5，v1.7.2）

本工具箱应从 ArcGIS Pro 内部运行。工具“00 一键初始化森林小班项目”
只操作当前打开的 ArcGIS Pro 项目，不从外部创建 APRX，也不调用 CIM setDefinition。
"""

import os
import datetime
import tempfile
import shutil
import json
import uuid

import arcpy


TOOLBOX_VERSION = "1.7.2"
MAX_TRACK_FILE_BYTES = 500 * 1024 * 1024

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROJECT_DATA_DIR = os.path.dirname(TOOL_DIR)

FEATURE_SPECS = [
    # dataset, display name, visible, color RGB, outline RGB, size
    # 04 外业核对
    ("Boundary_Adjustment_Lines", "边界调整线", True, [255, 0, 255, 100], None, 2.0),
    ("Field_Check_Points", "外业核对点", False, [255, 0, 255, 100], [80, 0, 80, 100], 6.0),
    ("Photo_Points", "照片点", False, [0, 255, 255, 100], [0, 90, 90, 100], 6.0),
    ("Control_Plot_Centers", "控制样地中心", False, [0, 190, 0, 100], [0, 80, 0, 100], 7.0),
    ("Standard_Plot_Polygons", "标准样地", False, [80, 200, 80, 25], [0, 120, 0, 100], 1.5),
    # 03 两步路与导航
    ("TwoSteps_Track_Lines", "两步路轨迹线", True, [0, 255, 255, 100], None, 2.0),
    ("TwoSteps_Track_Points", "两步路轨迹点", False, [255, 120, 0, 100], [120, 50, 0, 100], 4.0),
    # 02 小班区划（作业边界置于候选小班上方）
    ("Work_Boundary", "作业边界", True, [255, 255, 255, 0], [230, 0, 0, 100], 2.5),
    ("Xiaoban_Preliminary", "候选小班", True, [255, 255, 0, 0], [255, 255, 0, 100], 1.6),
    ("Xiaoban_Centers", "小班中心点", False, [255, 215, 0, 100], [80, 80, 80, 100], 5.0),
]

RASTER_SPECS = [
    (os.path.join("Data", "imagery_clip.tif"), "影像_作业区裁剪", True),
    (os.path.join("Data", "imagery_full.tif"), "影像_原始全幅", False),
    (os.path.join("Data", "DEM", "slope_deg.tif"), "坡度（度）", False),
    (os.path.join("Data", "DEM", "dem_clip.tif"), "DEM_作业区", False),
]

GROUP_ORDER = ["04 外业核对", "03 两步路与导航", "02 小班区划", "01 影像与地形"]
FEATURE_GROUPS = {
    "Boundary_Adjustment_Lines": "04 外业核对",
    "Field_Check_Points": "04 外业核对",
    "Photo_Points": "04 外业核对",
    "Control_Plot_Centers": "04 外业核对",
    "Standard_Plot_Polygons": "04 外业核对",
    "TwoSteps_Track_Lines": "03 两步路与导航",
    "TwoSteps_Track_Points": "03 两步路与导航",
    "Work_Boundary": "02 小班区划",
    "Xiaoban_Preliminary": "02 小班区划",
    "Xiaoban_Centers": "02 小班区划",
}
RASTER_GROUP = "01 影像与地形"
MANAGED_GROUP_NAMES = set(GROUP_ORDER)
MANAGED_DISPLAY_NAMES = {spec[1] for spec in FEATURE_SPECS} | {spec[1] for spec in RASTER_SPECS}


class Toolbox(object):
    def __init__(self):
        self.label = "森林小班区划与踏查工具"
        self.alias = "forestxb"
        self.tools = [
            InitializeProject,
            ImportTracks,
            UpdateGeometry,
            SelfCheck,
        ]


def _message(text):
    arcpy.AddMessage(text)


def _warning(text):
    arcpy.AddWarning(text)


def _project_and_map(map_name="森林小班区划"):
    try:
        aprx = arcpy.mp.ArcGISProject("CURRENT")
    except Exception as exc:
        raise RuntimeError(
            "本工具必须在 ArcGIS Pro 内部运行。请先新建或打开一个 ArcGIS Pro 项目，"
            "再从目录窗格运行本工具箱。原始错误：{}".format(exc)
        )

    current_map = aprx.activeMap
    if current_map is not None and current_map.mapType == "MAP":
        return aprx, current_map, False

    maps = [m for m in aprx.listMaps() if m.mapType == "MAP"]
    if maps:
        return aprx, maps[0], False

    new_map = aprx.createMap(map_name, "MAP")
    try:
        new_map.openView()
    except Exception:
        pass
    return aprx, new_map, True


def _normalize_path(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _layer_source(layer):
    try:
        if layer.supports("DATASOURCE"):
            return _normalize_path(layer.dataSource)
    except Exception:
        return None
    return None


def _remove_existing_managed_layers(map_obj, source_paths):
    source_set = {_normalize_path(p) for p in source_paths}
    removed = 0

    # 先删除本工具创建的任务分组；删除组会同时移除其子图层。
    for layer in list(map_obj.listLayers()):
        try:
            if getattr(layer, "isGroupLayer", False) and layer.name in MANAGED_GROUP_NAMES:
                map_obj.removeLayer(layer)
                removed += 1
        except Exception as exc:
            _warning("无法移除已有图层组 {}：{}".format(layer.name, exc))

    # 再清理历史版本遗留在根目录的同源或同名图层。
    for layer in list(map_obj.listLayers()):
        if getattr(layer, "isGroupLayer", False):
            continue
        source = _layer_source(layer)
        if source in source_set or layer.name in MANAGED_DISPLAY_NAMES:
            try:
                map_obj.removeLayer(layer)
                removed += 1
            except Exception as exc:
                _warning("无法移除已有图层 {}：{}".format(layer.name, exc))
    return removed


def _create_task_groups(map_obj):
    groups = {}
    # ArcGIS Pro顶部图层覆盖底部图层，因此按绘制层级固定为04→01：外业/轨迹/小班在上，影像在最下。
    for group_name in reversed(GROUP_ORDER):
        group = map_obj.createGroupLayer(group_name)
        group.visible = True
        try:
            group.setGroupType("CHECKBOX")
        except Exception:
            pass
        groups[group_name] = group

    # 明确固定根目录组顺序，避免不同 ArcGIS Pro 环境的新建位置差异。
    for group_name in reversed(GROUP_ORDER):
        _move_to_top(map_obj, groups[group_name])
    return groups


def _add_layer_to_group(map_obj, group_layer, layer):
    """复制图层到任务分组并移除根目录原图层。"""
    map_obj.addLayerToGroup(group_layer, layer, "BOTTOM")
    map_obj.removeLayer(layer)


def _apply_feature_style(layer, dataset_name, color, outline_color, size):
    try:
        sym = layer.symbology
        if not hasattr(sym, "renderer"):
            return
        sym.updateRenderer("SimpleRenderer")
        symbol = sym.renderer.symbol
        desc = arcpy.Describe(layer)
        shape_type = str(getattr(desc, "shapeType", "")).lower()

        if shape_type == "polygon":
            symbol.color = {"RGB": color}
            if outline_color is not None and hasattr(symbol, "outlineColor"):
                symbol.outlineColor = {"RGB": outline_color}
            if hasattr(symbol, "outlineWidth"):
                symbol.outlineWidth = size
            elif hasattr(symbol, "size"):
                symbol.size = size
        elif shape_type == "polyline":
            symbol.color = {"RGB": color}
            if hasattr(symbol, "size"):
                symbol.size = size
        elif shape_type == "point":
            symbol.color = {"RGB": color}
            if outline_color is not None and hasattr(symbol, "outlineColor"):
                symbol.outlineColor = {"RGB": outline_color}
            if hasattr(symbol, "size"):
                symbol.size = size

        layer.symbology = sym
    except Exception as exc:
        _warning("图层 {} 已加载，但基础符号化未完全应用：{}".format(dataset_name, exc))


def _enable_xiaoban_labels(layer):
    try:
        if not layer.supports("SHOWLABELS"):
            return
        field_names = {f.name.upper() for f in arcpy.ListFields(layer)}
        if "XB_ID" not in field_names:
            _warning("候选小班缺少 XB_ID 字段，未开启注记。")
            return
        classes = layer.listLabelClasses()
        if not classes:
            classes = [layer.createLabelClass("XB_ID", labelclass_language="Arcade")]
        # 使用Arcade文字格式标签实现白色、加粗、10pt；不调用CIM setDefinition。
        classes[0].expression = "\"<CLR red='255' green='255' blue='255'><FNT size='10'><BOL>\" + $feature.XB_ID + \"</BOL></FNT></CLR>\""
        classes[0].visible = True
        layer.showLabels = True
    except Exception as exc:
        _warning("候选小班已加载，但 XB_ID 注记未成功开启：{}".format(exc))


def _move_to_top(map_obj, layer):
    layers = map_obj.listLayers()
    if not layers or layers[0] == layer:
        return
    try:
        map_obj.moveLayer(layers[0], layer, "BEFORE")
    except Exception:
        pass


def _set_extent(aprx, map_obj, boundary_path):
    extent = arcpy.Describe(boundary_path).extent
    try:
        view = aprx.activeView
        if view is not None and hasattr(view, "camera"):
            view.camera.setExtent(extent)
            return
    except Exception:
        pass
    try:
        camera = map_obj.defaultCamera
        camera.setExtent(extent)
        map_obj.defaultCamera = camera
    except Exception as exc:
        _warning("数据已加载，但未自动缩放到作业边界：{}".format(exc))


class InitializeProject(object):
    def __init__(self):
        self.label = "00 一键初始化森林小班项目"
        self.description = (
            "在当前 ArcGIS Pro 项目中自动加载 ProjectData.gdb、裁剪/全幅影像、DEM和坡度，"
            "设置地图坐标系、四个任务图层组、默认可见性、黄色小班边界和清晰注记。普通用户只需选择项目数据目录。"
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        p0 = arcpy.Parameter(
            displayName="项目数据目录（包含 ProjectData.gdb 和 Data 文件夹）",
            name="project_data_dir",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input",
        )
        p0.value = DEFAULT_PROJECT_DATA_DIR
        return [p0]

    def updateMessages(self, parameters):
        root = parameters[0].valueAsText
        if not root:
            return
        gdb = os.path.join(root, "ProjectData.gdb")
        if not arcpy.Exists(gdb):
            parameters[0].setErrorMessage("所选目录中未发现 ProjectData.gdb：{}".format(gdb))
            return
        for required in ["Work_Boundary", "Xiaoban_Preliminary"]:
            path = os.path.join(gdb, required)
            if not arcpy.Exists(path):
                parameters[0].setErrorMessage("ProjectData.gdb 缺少必要要素类：{}".format(required))
                return

    def execute(self, parameters, messages):
        root = os.path.abspath(parameters[0].valueAsText)
        # 精简版固定采用安全默认值，避免学生误选参数。
        replace_existing = True
        apply_style = True
        save_project = True

        gdb = os.path.join(root, "ProjectData.gdb")
        if not arcpy.Exists(gdb):
            raise RuntimeError("未找到 ProjectData.gdb：{}".format(gdb))

        boundary_path = os.path.join(gdb, "Work_Boundary")
        xiaoban_path = os.path.join(gdb, "Xiaoban_Preliminary")
        for required_path in [boundary_path, xiaoban_path]:
            if not arcpy.Exists(required_path):
                raise RuntimeError("缺少必要数据：{}".format(required_path))

        aprx, map_obj, created_map = _project_and_map()
        if map_obj.name in ("地图", "Map", "森林小班区划"):
            try:
                map_obj.name = "小班区划工作图"
            except Exception:
                pass
        _message("当前地图：{}{}".format(map_obj.name, "（新建）" if created_map else ""))

        target_sr = arcpy.Describe(boundary_path).spatialReference
        if target_sr is not None and target_sr.name not in (None, "Unknown"):
            map_obj.spatialReference = target_sr
            _message("地图坐标系已设置为：{}".format(target_sr.name))
        else:
            _warning("作业边界坐标系未知，未修改地图坐标系。")

        source_paths = []
        for dataset_name, _, _, _, _, _ in FEATURE_SPECS:
            source_paths.append(os.path.join(gdb, dataset_name))
        for relative_path, _, _ in RASTER_SPECS:
            source_paths.append(os.path.join(root, relative_path))

        if replace_existing:
            removed = _remove_existing_managed_layers(map_obj, source_paths)
            if removed:
                _message("已移除 {} 个旧的同源/同名图层。".format(removed))

        groups = _create_task_groups(map_obj)
        added_count = 0
        missing_optional = []

        for dataset_name, display_name, visible, color, outline, size in FEATURE_SPECS:
            path = os.path.join(gdb, dataset_name)
            if not arcpy.Exists(path):
                if dataset_name in ("Work_Boundary", "Xiaoban_Preliminary"):
                    raise RuntimeError("缺少必要要素类：{}".format(dataset_name))
                missing_optional.append(dataset_name)
                continue
            layer = map_obj.addDataFromPath(path)
            layer.name = display_name
            layer.visible = visible
            if apply_style:
                _apply_feature_style(layer, dataset_name, color, outline, size)
                if dataset_name == "Xiaoban_Preliminary":
                    _enable_xiaoban_labels(layer)
            _add_layer_to_group(map_obj, groups[FEATURE_GROUPS[dataset_name]], layer)
            added_count += 1

        for relative_path, display_name, visible in RASTER_SPECS:
            path = os.path.join(root, relative_path)
            if not os.path.exists(path):
                missing_optional.append(relative_path)
                continue
            layer = map_obj.addDataFromPath(path)
            layer.name = display_name
            layer.visible = visible
            _add_layer_to_group(map_obj, groups[RASTER_GROUP], layer)
            added_count += 1

        _set_extent(aprx, map_obj, boundary_path)

        if save_project:
            if getattr(aprx, "isReadOnly", False):
                _warning("当前项目为只读，数据已加载但无法自动保存。请手动另存项目。")
            else:
                aprx.save()
                _message("当前 ArcGIS Pro 项目已保存。")

        if missing_optional:
            _warning("以下可选数据未找到，已跳过：{}".format("、".join(missing_optional)))

        _message("一键初始化完成：已加载 {} 个图层，并整理为4个任务图层组。".format(added_count))
        _message("默认显示：裁剪影像、候选小班、作业边界、两步路轨迹线和边界调整线。")
        _message("默认关闭：小班中心点、外业点、照片点、控制样地、标准样地、轨迹点、全幅影像、DEM和坡度。")
        _message("候选小班仍需结合影像、外业踏查和教师意见人工核查后定版。")



def _field_lookup(dataset):
    return {f.name.upper(): f.name for f in arcpy.ListFields(dataset)}


def _pick_field(dataset, candidates):
    lookup = _field_lookup(dataset)
    for candidate in candidates:
        actual = lookup.get(candidate.upper())
        if actual:
            return actual
    return None


def _count_rows(dataset):
    return int(arcpy.management.GetCount(dataset)[0])


def _infer_project_data_dir():
    """Prefer the toolbox-adjacent project, then infer from active map data sources."""
    candidate = DEFAULT_PROJECT_DATA_DIR
    if arcpy.Exists(os.path.join(candidate, "ProjectData.gdb")):
        return candidate
    try:
        aprx = arcpy.mp.ArcGISProject("CURRENT")
        map_obj = aprx.activeMap
        if map_obj is None:
            maps = [m for m in aprx.listMaps() if m.mapType == "MAP"]
            map_obj = maps[0] if maps else None
        if map_obj is not None:
            for layer in map_obj.listLayers():
                source = _layer_source(layer)
                if not source:
                    continue
                marker = os.sep + "ProjectData.gdb" + os.sep
                if marker.lower() in source.lower():
                    gdb = source[: source.lower().index(marker.lower()) + len(os.sep + "ProjectData.gdb")]
                    root = os.path.dirname(gdb)
                    if arcpy.Exists(os.path.join(root, "ProjectData.gdb")):
                        return root
    except Exception:
        pass
    return DEFAULT_PROJECT_DATA_DIR


def _validate_project_data_dir(root):
    root = os.path.abspath(root)
    gdb = os.path.join(root, "ProjectData.gdb")
    required = [
        gdb,
        os.path.join(gdb, "Work_Boundary"),
        os.path.join(gdb, "Xiaoban_Preliminary"),
        os.path.join(gdb, "TwoSteps_Track_Points"),
        os.path.join(gdb, "TwoSteps_Track_Lines"),
    ]
    missing = [path for path in required if not arcpy.Exists(path)]
    if missing:
        raise RuntimeError("项目数据目录不完整，缺少：{}".format("；".join(missing)))
    return root, gdb


def _is_unknown_sr(sr):
    return sr is None or getattr(sr, "name", None) in (None, "", "Unknown")


def _same_sr(a, b):
    if _is_unknown_sr(a) or _is_unknown_sr(b):
        return False
    if getattr(a, "factoryCode", 0) and getattr(b, "factoryCode", 0):
        return a.factoryCode == b.factoryCode
    try:
        return a.exportToString() == b.exportToString()
    except Exception:
        return a.name == b.name


def _assign_sr_without_projection(geometry, sr):
    geom_type = geometry.type.lower()
    if geom_type == "point":
        point = geometry.firstPoint
        return arcpy.PointGeometry(arcpy.Point(point.X, point.Y), sr)
    if geom_type == "polyline":
        parts = arcpy.Array()
        for part in geometry:
            arr = arcpy.Array()
            for point in part:
                if point is not None:
                    arr.add(arcpy.Point(point.X, point.Y))
            if len(arr) >= 2:
                parts.add(arr)
        if len(parts) == 0:
            return None
        return arcpy.Polyline(parts, sr)
    return None


def _drop_zm(geometry, target_sr):
    geom_type = geometry.type.lower()
    if geom_type == "point":
        point = geometry.firstPoint
        if point is None:
            return None
        return arcpy.PointGeometry(arcpy.Point(point.X, point.Y), target_sr)
    if geom_type == "polyline":
        parts = arcpy.Array()
        for part in geometry:
            arr = arcpy.Array()
            for point in part:
                if point is not None:
                    arr.add(arcpy.Point(point.X, point.Y))
            if len(arr) >= 2:
                parts.add(arr)
        if len(parts) == 0:
            return None
        return arcpy.Polyline(parts, target_sr)
    return None


def _project_geometry_2d(geometry, target_sr, assume_wgs84=False):
    if geometry is None or int(getattr(geometry, "pointCount", 0)) == 0:
        return None
    source_sr = geometry.spatialReference
    if _is_unknown_sr(source_sr):
        if not assume_wgs84:
            raise RuntimeError("输入轨迹几何缺少坐标系，无法安全导入。")
        source_sr = arcpy.SpatialReference(4326)
        geometry = _assign_sr_without_projection(geometry, source_sr)
        if geometry is None:
            return None
    if not _same_sr(source_sr, target_sr):
        transformation = None
        try:
            transformations = arcpy.ListTransformations(source_sr, target_sr, geometry.extent)
            transformation = transformations[0] if transformations else None
        except Exception:
            transformation = None
        geometry = geometry.projectAs(target_sr, transformation) if transformation else geometry.projectAs(target_sr)
    return _drop_zm(geometry, target_sr)


def _new_id(prefix):
    return "{}-{}".format(prefix, uuid.uuid4().hex[:12].upper())


def _append_points(source_fc, target_fc, source_name, target_sr, assume_wgs84=False):
    type_field = _pick_field(source_fc, ["TYPE", "POINT_TYPE", "FEATURETYPE"])
    name_field = _pick_field(source_fc, ["NAME", "TITLE", "TRACK_NAME"])
    read_fields = ["SHAPE@"]
    if type_field:
        read_fields.append(type_field)
    if name_field and name_field not in read_fields:
        read_fields.append(name_field)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted = 0
    with arcpy.da.SearchCursor(source_fc, read_fields) as src, arcpy.da.InsertCursor(
        target_fc,
        ["SHAPE@", "POINT_ID", "POINT_TYPE", "SOURCE_FILE", "IMPORT_TIME", "REMARK"],
    ) as dst:
        for row in src:
            geometry = _project_geometry_2d(row[0], target_sr, assume_wgs84=assume_wgs84)
            if geometry is None:
                continue
            index = 1
            point_type = str(row[index]) if type_field and row[index] not in (None, "") else "轨迹点"
            if type_field:
                index += 1
            name = str(row[index]) if name_field and row[index] not in (None, "") else ""
            dst.insertRow([
                geometry,
                _new_id("TP"),
                point_type[:50],
                source_name[:255],
                now,
                name[:255],
            ])
            inserted += 1
    return inserted


def _append_lines(source_fc, target_fc, source_name, target_sr, assume_wgs84=False):
    name_field = _pick_field(source_fc, ["NAME", "TITLE", "TRACK_NAME"])
    read_fields = ["SHAPE@"] + ([name_field] if name_field else [])
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted = 0
    with arcpy.da.SearchCursor(source_fc, read_fields) as src, arcpy.da.InsertCursor(
        target_fc,
        ["SHAPE@", "TRACK_ID", "TRACK_NAME", "SOURCE_FILE", "IMPORT_TIME", "REMARK"],
    ) as dst:
        for row in src:
            geometry = _project_geometry_2d(row[0], target_sr, assume_wgs84=assume_wgs84)
            if geometry is None:
                continue
            name = str(row[1]) if name_field and len(row) > 1 and row[1] not in (None, "") else os.path.splitext(source_name)[0]
            dst.insertRow([
                geometry,
                _new_id("TR"),
                name[:100],
                source_name[:255],
                now,
                "由轨迹文件导入",
            ])
            inserted += 1
    return inserted


def _walk_feature_classes(workspace):
    results = []
    for dirpath, _, filenames in arcpy.da.Walk(workspace, datatype="FeatureClass"):
        for filename in filenames:
            results.append(os.path.join(dirpath, filename))
    return results


def _create_staging_fc(temp_gdb, name, geometry_type, template, target_sr):
    out_fc = os.path.join(temp_gdb, name)
    arcpy.management.CreateFeatureclass(
        temp_gdb,
        name,
        geometry_type,
        template=template,
        has_m="DISABLED",
        has_z="DISABLED",
        spatial_reference=target_sr,
    )
    return out_fc


def _copy_for_rollback(source_fc, temp_gdb, name):
    out_fc = os.path.join(temp_gdb, name)
    arcpy.management.CopyFeatures(source_fc, out_fc)
    return out_fc


def _commit_tracks(staging_points, staging_lines, target_points, target_lines, mode, temp_gdb):
    backup_points = _copy_for_rollback(target_points, temp_gdb, "backup_points")
    backup_lines = _copy_for_rollback(target_lines, temp_gdb, "backup_lines")
    try:
        if mode == "替换现有轨迹":
            arcpy.management.DeleteRows(target_points)
            arcpy.management.DeleteRows(target_lines)
        if _count_rows(staging_points):
            arcpy.management.Append(staging_points, target_points, "NO_TEST")
        if _count_rows(staging_lines):
            arcpy.management.Append(staging_lines, target_lines, "NO_TEST")
    except Exception:
        try:
            arcpy.management.DeleteRows(target_points)
            arcpy.management.DeleteRows(target_lines)
            if _count_rows(backup_points):
                arcpy.management.Append(backup_points, target_points, "NO_TEST")
            if _count_rows(backup_lines):
                arcpy.management.Append(backup_lines, target_lines, "NO_TEST")
        except Exception as restore_exc:
            _warning("轨迹写入失败且自动恢复也失败，请不要继续编辑目标图层：{}".format(restore_exc))
        raise


def _has_spatial_intersection(dataset, boundary):
    if _count_rows(dataset) == 0:
        return False
    layer_name = "forestgis_track_check_{}".format(uuid.uuid4().hex[:8])
    try:
        arcpy.management.MakeFeatureLayer(dataset, layer_name)
        arcpy.management.SelectLayerByLocation(layer_name, "INTERSECT", boundary, selection_type="NEW_SELECTION")
        return _count_rows(layer_name) > 0
    finally:
        try:
            arcpy.management.Delete(layer_name)
        except Exception:
            pass


def _write_json_report(path, payload):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


class ImportTracks(object):
    def __init__(self):
        self.label = "01 导入两步路轨迹"
        self.description = (
            "先在临时工作区完成转换和验证，再一次性写入ProjectData.gdb；"
            "失败时恢复原轨迹。支持GPX、KML/KMZ、GeoJSON和Esri JSON。"
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        p0 = arcpy.Parameter(
            displayName="项目数据目录（包含 ProjectData.gdb）",
            name="project_data_dir",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input",
        )
        p0.value = _infer_project_data_dir()

        p1 = arcpy.Parameter(
            displayName="轨迹文件",
            name="files",
            datatype="DEFile",
            parameterType="Required",
            direction="Input",
            multiValue=True,
        )
        p1.filter.list = ["gpx", "kml", "kmz", "geojson", "json"]

        p2 = arcpy.Parameter(
            displayName="导入方式",
            name="import_mode",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        p2.filter.type = "ValueList"
        p2.filter.list = ["替换现有轨迹", "追加到现有轨迹"]
        p2.value = "替换现有轨迹"

        return [p0, p1, p2]

    def updateMessages(self, parameters):
        root = parameters[0].valueAsText
        if root:
            try:
                _validate_project_data_dir(root)
            except Exception as exc:
                parameters[0].setErrorMessage(str(exc))

    def execute(self, parameters, messages):
        project_data_dir, gdb = _validate_project_data_dir(parameters[0].valueAsText)
        raw_files = parameters[1].valueAsText or ""
        files = [item.strip().strip("'").strip('"') for item in raw_files.split(";") if item.strip()]
        if not files:
            raise RuntimeError("没有选择轨迹文件。")
        for source_file in files:
            if not os.path.isfile(source_file):
                raise RuntimeError("轨迹文件不存在：{}".format(source_file))
            if os.path.getsize(source_file) > MAX_TRACK_FILE_BYTES:
                raise RuntimeError("轨迹文件超过500MB安全上限：{}".format(source_file))
            if os.path.splitext(source_file)[1].lower() not in (".gpx", ".kml", ".kmz", ".geojson", ".json"):
                raise RuntimeError("不支持的轨迹格式：{}".format(source_file))

        import_mode = parameters[2].valueAsText or "替换现有轨迹"
        show_after_import = True
        target_points = os.path.join(gdb, "TwoSteps_Track_Points")
        target_lines = os.path.join(gdb, "TwoSteps_Track_Lines")
        boundary = os.path.join(gdb, "Work_Boundary")
        target_sr = arcpy.Describe(boundary).spatialReference
        if _is_unknown_sr(target_sr):
            raise RuntimeError("作业边界坐标系未知，无法安全导入轨迹。")

        temp_root = tempfile.mkdtemp(prefix="forestgis_tracks_")
        report = {
            "toolbox_version": TOOLBOX_VERSION,
            "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "mode": import_mode,
            "source_files": [os.path.basename(path) for path in files],
            "staged_points": 0,
            "staged_lines": 0,
            "warnings": [],
            "status": "RUNNING",
        }
        try:
            temp_gdb = os.path.join(temp_root, "tracks.gdb")
            arcpy.management.CreateFileGDB(temp_root, "tracks.gdb")
            staging_points = _create_staging_fc(temp_gdb, "staging_points", "POINT", target_points, target_sr)
            staging_lines = _create_staging_fc(temp_gdb, "staging_lines", "POLYLINE", target_lines, target_sr)

            for index, source_file in enumerate(files, start=1):
                source_file = os.path.abspath(source_file)
                source_name = os.path.basename(source_file)
                ext = os.path.splitext(source_file)[1].lower()
                _message("正在暂存 {}：{}".format(index, source_name))
                feature_classes = []
                assume_wgs84 = ext in (".gpx", ".kml", ".kmz", ".geojson")

                if ext == ".gpx":
                    point_fc = os.path.join(temp_gdb, "gpx_points_{}".format(index))
                    line_fc = os.path.join(temp_gdb, "gpx_lines_{}".format(index))
                    arcpy.conversion.GPXtoFeatures(source_file, point_fc, "POINTS")
                    arcpy.conversion.GPXtoFeatures(source_file, line_fc, "TRACKS_AS_LINES")
                    feature_classes.extend([point_fc, line_fc])
                elif ext in (".kml", ".kmz"):
                    out_name = "kml_{}".format(index)
                    arcpy.conversion.KMLToLayer(source_file, temp_root, out_name)
                    gdb_candidates = [
                        os.path.join(temp_root, name)
                        for name in os.listdir(temp_root)
                        if name.lower().endswith(".gdb") and name.lower().startswith(out_name.lower())
                    ]
                    if len(gdb_candidates) != 1:
                        raise RuntimeError("KML转换结果不唯一，无法安全判断：{}".format(source_name))
                    feature_classes.extend(_walk_feature_classes(gdb_candidates[0]))
                elif ext == ".geojson":
                    for geometry_type, suffix in (("POINT", "points"), ("POLYLINE", "lines")):
                        out_fc = os.path.join(temp_gdb, "geojson_{}_{}".format(index, suffix))
                        arcpy.conversion.JSONToFeatures(source_file, out_fc, geometry_type)
                        feature_classes.append(out_fc)
                elif ext == ".json":
                    out_fc = os.path.join(temp_gdb, "json_{}".format(index))
                    arcpy.conversion.JSONToFeatures(source_file, out_fc)
                    feature_classes.append(out_fc)

                file_points = 0
                file_lines = 0
                for fc in feature_classes:
                    if not arcpy.Exists(fc) or _count_rows(fc) == 0:
                        continue
                    shape_type = str(arcpy.Describe(fc).shapeType).lower()
                    if shape_type == "point":
                        file_points += _append_points(fc, staging_points, source_name, target_sr, assume_wgs84=assume_wgs84)
                    elif shape_type == "polyline":
                        file_lines += _append_lines(fc, staging_lines, source_name, target_sr, assume_wgs84=assume_wgs84)
                if file_points == 0 and file_lines == 0:
                    report["warnings"].append("{} 未产生可导入的点或线".format(source_name))
                report["staged_points"] += file_points
                report["staged_lines"] += file_lines

            if report["staged_points"] == 0 and report["staged_lines"] == 0:
                raise RuntimeError("所有轨迹文件均未得到可导入的点或线，目标数据未被修改。")

            staged_spatial_dataset = staging_lines if report["staged_lines"] else staging_points
            intersects = _has_spatial_intersection(staged_spatial_dataset, boundary)
            if not intersects:
                report["warnings"].append(
                    "轨迹与作业边界没有真实空间相交，可能存在坐标系或GCJ-02/BD-09偏移。"
                )
                _warning(report["warnings"][-1])
            else:
                _message("轨迹与作业边界存在真实空间相交。")

            _commit_tracks(staging_points, staging_lines, target_points, target_lines, import_mode, temp_gdb)
            point_count = _count_rows(target_points)
            line_count = _count_rows(target_lines)

            try:
                aprx, map_obj, _ = _project_and_map()
                for layer_name in ["两步路轨迹点", "两步路轨迹线"]:
                    for layer in map_obj.listLayers(layer_name):
                        layer.visible = show_after_import
                for group in map_obj.listLayers("03 两步路与导航"):
                    if getattr(group, "isGroupLayer", False):
                        group.visible = True
                if not getattr(aprx, "isReadOnly", False):
                    aprx.save()
            except Exception as display_exc:
                report["warnings"].append("轨迹已写入，但地图显示或项目保存未完成：{}".format(display_exc))
                _warning(report["warnings"][-1])

            report.update({
                "status": "SUCCESS_WITH_WARNING" if report["warnings"] else "SUCCESS",
                "finished_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "target_point_count": point_count,
                "target_line_count": line_count,
                "intersects_boundary": intersects,
            })
            report_path = os.path.join(os.path.dirname(project_data_dir), "03_Reports", "track_import_report.json")
            try:
                _write_json_report(report_path, report)
            except Exception as report_exc:
                _warning("轨迹已写入，但导入报告未能保存：{}".format(report_exc))
            _message(
                "轨迹导入完成：暂存并写入 {} 个点、{} 条线；目标图层当前共 {} 个点、{} 条线。".format(
                    report["staged_points"], report["staged_lines"], point_count, line_count
                )
            )
            _message("导入报告：{}".format(report_path))
        except Exception as exc:
            report.update({
                "status": "FAILED",
                "finished_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "error": str(exc),
            })
            try:
                report_path = os.path.join(os.path.dirname(project_data_dir), "03_Reports", "track_import_report.json")
                _write_json_report(report_path, report)
            except Exception:
                pass
            raise
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)


class UpdateGeometry(object):
    def __init__(self):
        self.label = "02 更新小班面积、坐标和中心点"
        self.description = "保存编辑后，自动更新候选小班面积、中心经纬度，并重建Xiaoban_Centers。"
        self.canRunInBackground = False

    def getParameterInfo(self):
        p0 = arcpy.Parameter(
            displayName="项目数据目录（包含 ProjectData.gdb）",
            name="project_data_dir",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input",
        )
        p0.value = _infer_project_data_dir()
        return [p0]

    def updateMessages(self, parameters):
        root = parameters[0].valueAsText
        if root:
            try:
                _, gdb = _validate_project_data_dir(root)
                fc = os.path.join(gdb, "Xiaoban_Preliminary")
                if not arcpy.Exists(fc):
                    parameters[0].setErrorMessage("缺少候选小班图层：{}".format(fc))
            except Exception as exc:
                parameters[0].setErrorMessage(str(exc))

    def execute(self, parameters, messages):
        project_data_dir, gdb = _validate_project_data_dir(parameters[0].valueAsText)
        fc = os.path.join(gdb, "Xiaoban_Preliminary")
        if not arcpy.Exists(fc):
            raise RuntimeError("小班图层不存在：{}".format(fc))
        required_fields = ["AREA_HA", "CTR_LON", "CTR_LAT"]
        lookup = _field_lookup(fc)
        missing = [field for field in required_fields if field not in lookup]
        if missing:
            raise RuntimeError("小班图层缺少字段：{}".format("、".join(missing)))

        wgs84 = arcpy.SpatialReference(4326)
        updated = 0
        with arcpy.da.UpdateCursor(fc, ["SHAPE@", lookup["AREA_HA"], lookup["CTR_LON"], lookup["CTR_LAT"]]) as cursor:
            for geometry, _, _, _ in cursor:
                if geometry is None or int(getattr(geometry, "pointCount", 0)) == 0:
                    continue
                # Polygon.labelPoint 返回 arcpy.Point；Point 本身没有 projectAs。
                # 先包装为 PointGeometry，再投影到 WGS 84，最后读取坐标。
                label_point_geometry = arcpy.PointGeometry(
                    geometry.labelPoint, geometry.spatialReference
                )
                projected_label_point = label_point_geometry.projectAs(wgs84)
                point = projected_label_point.firstPoint
                if point is None:
                    raise RuntimeError("无法计算小班中心坐标。")
                cursor.updateRow([
                    geometry,
                    geometry.getArea("GEODESIC", "HECTARES"),
                    point.X,
                    point.Y,
                ])
                updated += 1

        target_centers = os.path.join(gdb, "Xiaoban_Centers")
        temp_root = tempfile.mkdtemp(prefix="forestgis_centers_")
        try:
            temp_gdb = os.path.join(temp_root, "centers.gdb")
            arcpy.management.CreateFileGDB(temp_root, "centers.gdb")
            temp_centers = os.path.join(temp_gdb, "new_centers")
            arcpy.management.FeatureToPoint(fc, temp_centers, "INSIDE")
            backup_centers = _copy_for_rollback(target_centers, temp_gdb, "backup_centers")
            try:
                arcpy.management.DeleteRows(target_centers)
                arcpy.management.Append(temp_centers, target_centers, "NO_TEST")
            except Exception:
                arcpy.management.DeleteRows(target_centers)
                arcpy.management.Append(backup_centers, target_centers, "NO_TEST")
                raise
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

        arcpy.AddMessage("已更新 {} 个小班的面积和中心坐标，并重建 {} 个中心点。".format(
            updated, _count_rows(target_centers)
        ))


class SelfCheck(object):
    def __init__(self):
        self.label = "03 检查项目成果"
        self.description = "检查项目数据、关键字段、记录数量、轨迹、小班中心点和几何问题；只报告，不自动修复。"
        self.canRunInBackground = False

    def getParameterInfo(self):
        p = arcpy.Parameter(
            displayName="项目数据目录",
            name="project_data_dir",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input",
        )
        p.value = _infer_project_data_dir()
        return [p]

    def execute(self, parameters, messages):
        root, gdb = _validate_project_data_dir(parameters[0].valueAsText)
        feature_requirements = {
            "Work_Boundary": [],
            "Xiaoban_Preliminary": ["XB_ID", "AREA_HA", "CTR_LON", "CTR_LAT"],
            "Xiaoban_Centers": ["XB_ID"],
            "TwoSteps_Track_Lines": ["TRACK_ID", "SOURCE_FILE"],
            "TwoSteps_Track_Points": ["POINT_ID", "SOURCE_FILE"],
            "Field_Check_Points": ["CHECK_ID"],
            "Boundary_Adjustment_Lines": ["ADJ_ID"],
            "Photo_Points": ["PHOTO_ID"],
            "Control_Plot_Centers": ["PLOT_ID"],
            "Standard_Plot_Polygons": ["PLOT_ID"],
        }
        issues = []
        counts = {}
        for name, required_fields in feature_requirements.items():
            path = os.path.join(gdb, name)
            if not arcpy.Exists(path):
                issues.append({"severity": "ERROR", "code": "MISSING_DATASET", "dataset": name})
                continue
            counts[name] = _count_rows(path)
            lookup = _field_lookup(path)
            missing_fields = [field for field in required_fields if field not in lookup]
            if missing_fields:
                issues.append({
                    "severity": "ERROR",
                    "code": "MISSING_FIELDS",
                    "dataset": name,
                    "fields": missing_fields,
                })

        xiaoban = os.path.join(gdb, "Xiaoban_Preliminary")
        centers = os.path.join(gdb, "Xiaoban_Centers")
        if arcpy.Exists(xiaoban) and arcpy.Exists(centers):
            if counts.get("Xiaoban_Preliminary") != counts.get("Xiaoban_Centers"):
                issues.append({
                    "severity": "WARNING",
                    "code": "CENTER_COUNT_MISMATCH",
                    "xiaoban": counts.get("Xiaoban_Preliminary"),
                    "centers": counts.get("Xiaoban_Centers"),
                })

        temp_root = tempfile.mkdtemp(prefix="forestgis_check_")
        try:
            geometry_table = os.path.join(temp_root, "geometry_check.dbf")
            if arcpy.Exists(xiaoban):
                arcpy.management.CheckGeometry(xiaoban, geometry_table, "OGC")
                geometry_problem_count = _count_rows(geometry_table) if arcpy.Exists(geometry_table) else 0
                if geometry_problem_count:
                    issues.append({
                        "severity": "ERROR",
                        "code": "GEOMETRY_PROBLEMS",
                        "dataset": "Xiaoban_Preliminary",
                        "count": geometry_problem_count,
                    })
            else:
                geometry_problem_count = None
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

        raster_paths = [
            os.path.join(root, "Data", "imagery_clip.tif"),
            os.path.join(root, "Data", "imagery_full.tif"),
        ]
        for path in raster_paths:
            if not os.path.isfile(path):
                issues.append({"severity": "WARNING", "code": "MISSING_RASTER", "path": os.path.basename(path)})

        status = "PASS" if not issues else ("FAIL" if any(i["severity"] == "ERROR" for i in issues) else "WARNING")
        report = {
            "toolbox_version": TOOLBOX_VERSION,
            "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "status": status,
            "counts": counts,
            "issues": issues,
        }
        report_path = os.path.join(os.path.dirname(root), "03_Reports", "toolbox_self_check.json")
        _write_json_report(report_path, report)
        if status == "FAIL":
            raise RuntimeError("自检发现 {} 个问题，其中包含错误。详见：{}".format(len(issues), report_path))
        if status == "WARNING":
            _warning("自检完成，发现 {} 个警告。详见：{}".format(len(issues), report_path))
        else:
            _message("自检通过。详见：{}".format(report_path))
