# -*- coding: utf-8 -*-
"""使用 ArcPy 深度验证最终 ProjectData.gdb。

该脚本只读检查，不自动 Repair Geometry，不修改成果。
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

import arcpy

REQUIRED_FIELDS = {
    "RECORD_UUID", "XB_ID", "XB_NUM", "AREA_HA", "CTR_LON", "CTR_LAT", "ELEV_M",
    "SLOPE_DEG", "AUTO_CLAS", "CHK_PRI", "TREE_SPEC", "ORIGIN",
    "AGE_GROUP", "CANOPY", "LAND_TYPE", "BOUND_OK", "SURVEY_DT",
    "REMARK", "STATUS",
}
REQUIRED_FEATURE_CLASSES = {
    "Work_Boundary": "POLYGON",
    "Xiaoban_Preliminary": "POLYGON",
    "Xiaoban_Centers": "POINT",
    "TwoSteps_Track_Lines": "POLYLINE",
    "TwoSteps_Track_Points": "POINT",
    "Field_Check_Points": "POINT",
    "Boundary_Adjustment_Lines": "POLYLINE",
    "Photo_Points": "POINT",
    "Control_Plot_Centers": "POINT",
    "Standard_Plot_Polygons": "POLYGON",
}


def count_rows(dataset: str) -> int:
    return int(arcpy.management.GetCount(dataset).getOutput(0))


def _is_empty_geom(geom) -> bool:
    """ArcGIS Pro 3.x 移除 .isEmpty；用 pointCount 替代。"""
    if geom is None:
        return True
    try:
        return int(geom.pointCount) == 0
    except Exception:
        return True


def union_geometries(geometries: list[Any]):
    merged = None
    for geom in geometries:
        if _is_empty_geom(geom):
            continue
        merged = geom if merged is None else merged.union(geom)
    return merged


def area_m2(geom) -> float:
    if _is_empty_geom(geom):
        return 0.0
    return float(geom.getArea("PLANAR", "SQUAREMETERS"))


def append_check(checks: list[dict[str, Any]], errors: list[str], item: str, ok: bool, error: str | None = None, **extra: Any) -> None:
    record = {"item": item, "ok": bool(ok)}
    record.update(extra)
    checks.append(record)
    if not ok and error:
        errors.append(error)


def check_geometry(fc: str) -> tuple[int, list[dict[str, Any]]]:
    scratch = arcpy.env.scratchGDB
    cleanup = False
    if not scratch or not arcpy.Exists(scratch):
        scratch = str(Path(tempfile.gettempdir()) / ("forest_gis_validation_%d_%d.gdb" % (os.getpid(), time.time_ns())))
        if not arcpy.Exists(scratch):
            arcpy.management.CreateFileGDB(str(Path(scratch).parent), Path(scratch).name)
        cleanup = True
    name = arcpy.ValidateTableName("Geometry_Issues_%d" % int(time.time() * 1000), scratch)
    table = os.path.join(scratch, name)
    rows: list[dict[str, Any]] = []
    try:
        arcpy.management.CheckGeometry(fc, table, "ESRI")
        if arcpy.Exists(table):
            fields = {f.name.upper(): f.name for f in arcpy.ListFields(table)}
            problem_field = fields.get("PROBLEM")
            oid_field = fields.get("FEATURE_ID") or fields.get("FEATUREID")
            use = [x for x in (oid_field, problem_field) if x]
            if use:
                with arcpy.da.SearchCursor(table, use) as cur:
                    for row in cur:
                        item: dict[str, Any] = {}
                        for field, value in zip(use, row):
                            item[field] = value
                        rows.append(item)
            issue_count = count_rows(table)
        else:
            issue_count = 0
    finally:
        if arcpy.Exists(table):
            arcpy.management.Delete(table)
        if cleanup and arcpy.Exists(scratch):
            try:
                arcpy.management.Delete(scratch)
            except Exception:
                pass
    return issue_count, rows[:100]


def main() -> int:
    ap = argparse.ArgumentParser(description="深度验证最终 ArcGIS FileGDB")
    ap.add_argument("--project", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--expected-count", type=int)
    ap.add_argument("--overlap-tolerance-m2", type=float, default=1.0)
    ap.add_argument("--gap-tolerance-m2", type=float, default=5.0)
    ap.add_argument("--outside-tolerance-m2", type=float, default=1.0)
    ap.add_argument("--min-coverage-ratio", type=float, default=0.999)
    ap.add_argument("--require-terrain", action="store_true")
    ap.add_argument("--require-projected-crs", action="store_true")
    ap.add_argument("--require-meter-unit", action="store_true")
    args = ap.parse_args()

    project = Path(args.project).resolve()
    report_path = Path(args.report).resolve()
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {}

    gdb = str(project / "ProjectData.gdb")
    append_check(checks, errors, "ProjectData.gdb存在", arcpy.Exists(gdb), "缺少 ProjectData.gdb", path=gdb)
    if not arcpy.Exists(gdb):
        result = {"project": str(project), "ok": False, "errors": errors, "warnings": warnings, "checks": checks}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    datasets: dict[str, str] = {}
    for name, expected_shape in REQUIRED_FEATURE_CLASSES.items():
        fc = os.path.join(gdb, name)
        exists = bool(arcpy.Exists(fc))
        actual_shape = None
        if exists:
            actual_shape = str(arcpy.Describe(fc).shapeType).upper()
            datasets[name] = fc
        append_check(
            checks, errors, f"图层存在:{name}", exists,
            f"缺少图层: {name}", path=fc, expected_shape=expected_shape, actual_shape=actual_shape,
        )
        if exists:
            append_check(
                checks, errors, f"几何类型:{name}", actual_shape == expected_shape,
                f"图层 {name} 几何类型错误: {actual_shape}，应为 {expected_shape}",
            )

    xfc = datasets.get("Xiaoban_Preliminary")
    bfc = datasets.get("Work_Boundary")
    cfc = datasets.get("Xiaoban_Centers")
    if xfc:
        desc = arcpy.Describe(xfc)
        sr = desc.spatialReference
        sr_info = {
            "name": sr.name,
            "factory_code": int(sr.factoryCode or 0),
            "type": sr.type,
            "linear_unit": sr.linearUnitName,
        }
        details["spatial_reference"] = sr_info
        if args.require_projected_crs:
            append_check(checks, errors, "小班使用投影坐标系", str(sr.type).lower() == "projected", "最终小班不是投影坐标系", **sr_info)
        if args.require_meter_unit:
            linear = str(sr.linearUnitName or "").lower()
            append_check(checks, errors, "小班线性单位为米", linear.startswith("met"), f"最终小班线性单位不是米: {sr.linearUnitName}", **sr_info)

        fields = {f.name.upper(): f for f in arcpy.ListFields(xfc)}
        missing = sorted(REQUIRED_FIELDS - set(fields))
        append_check(checks, errors, "小班字段完整", not missing, "缺少字段: " + ",".join(missing) if missing else None, missing=missing)

        total = count_rows(xfc)
        append_check(checks, errors, "小班数量大于0", total > 0, "小班要素为空", value=total)
        if args.expected_count is not None:
            append_check(checks, errors, "小班数量符合预期", total == args.expected_count, f"小班数量 {total} 与预期 {args.expected_count} 不一致", expected=args.expected_count, actual=total)

        cursor_fields = ["OID@", "RECORD_UUID", "XB_ID", "SHAPE@"]
        for optional in ("ELEV_M", "SLOPE_DEG"):
            if optional in fields:
                cursor_fields.append(optional)
        rows = []
        null_geometry = 0
        null_id = 0
        null_uuid = 0
        terrain_nulls = []
        with arcpy.da.SearchCursor(xfc, cursor_fields) as cur:
            for row in cur:
                item = dict(zip(cursor_fields, row))
                geom = item["SHAPE@"]
                if _is_empty_geom(geom):
                    null_geometry += 1
                if item.get("XB_ID") in (None, ""):
                    null_id += 1
                if item.get("RECORD_UUID") in (None, ""):
                    null_uuid += 1
                if args.require_terrain and (item.get("ELEV_M") is None or item.get("SLOPE_DEG") is None):
                    terrain_nulls.append(item.get("XB_ID") or item.get("OID@"))
                rows.append(item)
        ids = [str(x.get("XB_ID")) for x in rows if x.get("XB_ID") not in (None, "")]
        uuids = [str(x.get("RECORD_UUID")) for x in rows if x.get("RECORD_UUID") not in (None, "")]
        duplicate_ids = sorted(k for k, v in Counter(ids).items() if v > 1)
        duplicate_uuids = sorted(k for k, v in Counter(uuids).items() if v > 1)
        append_check(checks, errors, "无空几何", null_geometry == 0, f"发现 {null_geometry} 个空几何", count=null_geometry)
        append_check(checks, errors, "XB_ID非空", null_id == 0, f"发现 {null_id} 个空 XB_ID", count=null_id)
        append_check(checks, errors, "XB_ID唯一", not duplicate_ids, "发现重复 XB_ID: " + ",".join(duplicate_ids) if duplicate_ids else None, duplicates=duplicate_ids)
        append_check(checks, errors, "RECORD_UUID非空", null_uuid == 0, f"发现 {null_uuid} 个空 RECORD_UUID", count=null_uuid)
        append_check(checks, errors, "RECORD_UUID唯一", not duplicate_uuids, "发现重复 RECORD_UUID: " + ",".join(duplicate_uuids) if duplicate_uuids else None, duplicates=duplicate_uuids)
        if args.require_terrain:
            append_check(checks, errors, "DEM统计已回写", not terrain_nulls, f"发现 {len(terrain_nulls)} 个小班缺少 ELEV_M/SLOPE_DEG", ids=terrain_nulls[:100])

        geom_issue_count, geom_issues = check_geometry(xfc)
        append_check(checks, errors, "ArcGIS几何检查通过", geom_issue_count == 0, f"Check Geometry 发现 {geom_issue_count} 个问题", issue_count=geom_issue_count, sample=geom_issues)

        valid_geometries = [(x["OID@"], x["XB_ID"], x["SHAPE@"]) for x in rows if not _is_empty_geom(x["SHAPE@"])]
        try:
            overlap_total = 0.0
            overlap_pairs = []
            for i, (oid1, id1, g1) in enumerate(valid_geometries):
                for oid2, id2, g2 in valid_geometries[i + 1:]:
                    if g1.disjoint(g2):
                        continue
                    inter = g1.intersect(g2, 4)
                    value = area_m2(inter)
                    if value > 0:
                        overlap_total += value
                        if value > args.overlap_tolerance_m2:
                            overlap_pairs.append({"a": id1 or oid1, "b": id2 or oid2, "area_m2": value})
            append_check(
                checks, errors, "小班无明显重叠", overlap_total <= args.overlap_tolerance_m2,
                f"小班重叠面积 {overlap_total:.3f} m² 超过容差 {args.overlap_tolerance_m2:.3f} m²",
                total_area_m2=overlap_total, tolerance_m2=args.overlap_tolerance_m2, pairs=overlap_pairs[:100],
            )

            if bfc:
                boundaries = [r[0] for r in arcpy.da.SearchCursor(bfc, ["SHAPE@"]) if not _is_empty_geom(r[0])]
                boundary_union = union_geometries(boundaries)
                compartment_union = union_geometries([x[2] for x in valid_geometries])
                if boundary_union is None or compartment_union is None:
                    append_check(checks, errors, "面积覆盖可计算", False, "无法计算边界与小班覆盖")
                else:
                    boundary_area = area_m2(boundary_union)
                    gap_area = area_m2(boundary_union.difference(compartment_union))
                    outside_area = area_m2(compartment_union.difference(boundary_union))
                    intersection_area = area_m2(boundary_union.intersect(compartment_union, 4))
                    coverage_ratio = intersection_area / boundary_area if boundary_area > 0 else 0.0
                    details["coverage"] = {
                        "boundary_area_m2": boundary_area,
                        "gap_area_m2": gap_area,
                        "outside_area_m2": outside_area,
                        "coverage_ratio": coverage_ratio,
                    }
                    append_check(checks, errors, "边界内缺口不超容差", gap_area <= args.gap_tolerance_m2, f"边界内缺口 {gap_area:.3f} m² 超过容差 {args.gap_tolerance_m2:.3f} m²", value=gap_area, tolerance=args.gap_tolerance_m2)
                    append_check(checks, errors, "小班不明显越界", outside_area <= args.outside_tolerance_m2, f"小班越界 {outside_area:.3f} m² 超过容差 {args.outside_tolerance_m2:.3f} m²", value=outside_area, tolerance=args.outside_tolerance_m2)
                    append_check(checks, errors, "覆盖率达标", coverage_ratio >= args.min_coverage_ratio, f"覆盖率 {coverage_ratio:.6f} 低于阈值 {args.min_coverage_ratio:.6f}", value=coverage_ratio, threshold=args.min_coverage_ratio)
        except Exception as exc:
            append_check(checks, errors, "拓扑面积检查可执行", False, f"拓扑面积检查失败: {type(exc).__name__}: {exc}")

        if cfc:
            center_count = count_rows(cfc)
            append_check(checks, errors, "中心点数量与小班一致", center_count == total, f"中心点数量 {center_count} 与小班数量 {total} 不一致", centers=center_count, compartments=total)

    incomplete = project / "_BUILD_INCOMPLETE.json"
    append_check(checks, errors, "构建完成标记正常", not incomplete.exists(), "仍存在 _BUILD_INCOMPLETE.json，构建可能未完成", path=str(incomplete))

    result = {
        "project": str(project),
        "gdb": gdb,
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "details": details,
        "policy": {
            "expected_count": args.expected_count,
            "overlap_tolerance_m2": args.overlap_tolerance_m2,
            "gap_tolerance_m2": args.gap_tolerance_m2,
            "outside_tolerance_m2": args.outside_tolerance_m2,
            "min_coverage_ratio": args.min_coverage_ratio,
            "require_terrain": args.require_terrain,
            "require_projected_crs": args.require_projected_crs,
            "require_meter_unit": args.require_meter_unit,
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    report_path.write_text(text, encoding="utf-8")
    print(text)
    return 0 if not errors else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        payload = {
            "ok": False,
            "errors": [f"{type(exc).__name__}: {exc}"],
            "status": "SCRIPT_ERROR",
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        raise SystemExit(4)
