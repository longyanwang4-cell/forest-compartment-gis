#!/usr/bin/env python3
"""validate_topology.py - 森林小班拓扑校验（Rook/Queen 邻接、多部件、连通性、重叠）。

可独立从命令行运行，无需经过 WorkBuddy 或 forest-gis.ps1：

    python validate_topology.py --gpkg <forest_compartments.gpkg> \
        [--layer xiaoban_preliminary] [--report <out.json>]

设计原则：
- Rook 邻接 = 两几何 boundary 交集的线状长度 > ROOK_LENGTH_TOLERANCE_M（1 mm）。
- Queen 邻接 = Rook，或两几何至少共点接触。
- 正面积重叠单独记录，不视作普通邻接；仅 > OVERLAP_WARNING_TOLERANCE_M2 标记为 WARNING。
- 真正多部件 = part_count > 1（而非 geom_type == "MultiPolygon"）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---- 集中定义的容差（在报告中显式区分） ----
ROOK_LENGTH_TOLERANCE_M = 0.001       # 共边长度阈值（米）：> 此值才算 Rook 共边
OVERLAP_NOISE_TOLERANCE_M2 = 1e-6     # 交叠面积记录下限（m²）：> 此值记录原始交叠值
OVERLAP_WARNING_TOLERANCE_M2 = 1.0    # 正式重叠警告阈值（m²）：> 此值标记 WARNING


def extract_linear_length(geometry):
    """递归提取几何对象中所有线状部分的长度（米）。

    即使 geometry 是 GeometryCollection，也会计入其中的 LineString / MultiLineString，
    避免把真实线段漏掉。
    """
    if geometry is None or geometry.is_empty:
        return 0.0

    geometry_type = geometry.geom_type

    if geometry_type == "LineString":
        return geometry.length

    if geometry_type == "MultiLineString":
        return sum(part.length for part in geometry.geoms)

    if geometry_type == "GeometryCollection":
        return sum(extract_linear_length(part) for part in geometry.geoms)

    return 0.0


def part_info(geom):
    """返回 (part_count, is_true_multipart, geometry_type, [每部件面积])。"""
    if geom.geom_type == "MultiPolygon":
        parts = list(geom.geoms)
        part_count = len(parts)
    else:
        parts = [geom]
        part_count = 1
    is_true_multipart = part_count > 1
    part_areas = [round(float(p.area), 6) for p in parts]
    return part_count, is_true_multipart, geom.geom_type, part_areas


def components(nodes, edges):
    """BFS 求连通分量。edges: list of (a, b) 或含更多字段的序列（取前两元素）。"""
    adj = {n: [] for n in nodes}
    for e in edges:
        a, b = e[0], e[1]
        adj[a].append(b)
        adj[b].append(a)
    seen = set()
    comps = []
    for n in nodes:
        if n in seen:
            continue
        stack = [n]
        comp = []
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            comp.append(x)
            stack.extend(adj[x])
        comps.append(sorted(comp))
    return comps


def validate_topology(gpkg, layer="xiaoban_preliminary"):
    import geopandas as gpd

    gdf = gpd.read_file(gpkg, layer=layer)
    if "XB_ID" in gdf.columns:
        ids = gdf["XB_ID"].tolist()
    else:
        ids = [f"R{i + 1}" for i in range(len(gdf))]
    geoms = gdf.geometry.tolist()
    n = len(geoms)
    crs = gdf.crs
    epsg = crs.to_epsg() if crs else None

    # 每小班多部件信息
    compartments = []
    for k in range(n):
        pc, ismp, gt, pa = part_info(geoms[k])
        compartments.append({
            "xb_id": ids[k],
            "geometry_type": gt,
            "part_count": pc,
            "is_true_multipart": ismp,
            "part_areas": pa,
            "total_area_ha": round(float(geoms[k].area) / 10000.0, 6),
        })

    rook_edges = []   # (i, j, length_m)
    queen_edges = []  # (i, j)
    overlaps = []     # {pair, area_m2, is_overlap_warning}

    for i in range(n):
        for j in range(i + 1, n):
            a = geoms[i]
            b = geoms[j]
            # 共边/共点判定：基于 boundary 交集的线状长度
            shared = a.boundary.intersection(b.boundary)
            shared_len = extract_linear_length(shared)
            is_rook = shared_len > ROOK_LENGTH_TOLERANCE_M
            is_queen = is_rook or (not shared.is_empty)
            if is_rook:
                rook_edges.append([ids[i], ids[j], round(shared_len, 6)])
            if is_queen:
                queen_edges.append([ids[i], ids[j]])

            # 重叠（正面积）：与邻接分开记录，不当作普通邻接
            poly_shared = a.intersection(b)
            if not poly_shared.is_empty:
                parea = float(poly_shared.area)
                if parea > OVERLAP_NOISE_TOLERANCE_M2:
                    is_warn = parea > OVERLAP_WARNING_TOLERANCE_M2
                    overlaps.append({
                        "pair": f"{ids[i]}_{ids[j]}",
                        "area_m2": round(parea, 6),
                        "is_overlap_warning": bool(is_warn),
                    })

    def degree(edges):
        d = {x: 0 for x in ids}
        for e in edges:
            d[e[0]] += 1
            d[e[1]] += 1
        return d

    rook_deg = degree(rook_edges)
    queen_deg = degree(queen_edges)
    rook_comps = components(ids, rook_edges)
    queen_comps = components(ids, queen_edges)

    report = {
        "gpkg": str(gpkg),
        "layer": layer,
        "crs": f"EPSG:{epsg}" if epsg else None,
        "compartment_count": n,
        "tolerances": {
            "ROOK_LENGTH_TOLERANCE_M": ROOK_LENGTH_TOLERANCE_M,
            "OVERLAP_NOISE_TOLERANCE_M2": OVERLAP_NOISE_TOLERANCE_M2,
            "OVERLAP_WARNING_TOLERANCE_M2": OVERLAP_WARNING_TOLERANCE_M2,
        },
        "rook": {
            "edge_count": len(rook_edges),
            "edges": [{"a": e[0], "b": e[1], "length_m": e[2]} for e in rook_edges],
            "degree": rook_deg,
            "connected": len(rook_comps) == 1,
            "component_count": len(rook_comps),
            "components": rook_comps,
        },
        "queen": {
            "edge_count": len(queen_edges),
            "edges": [{"a": e[0], "b": e[1]} for e in queen_edges],
            "degree": queen_deg,
            "connected": len(queen_comps) == 1,
            "component_count": len(queen_comps),
            "components": queen_comps,
        },
        "overlaps": overlaps,
        "overlap_warning_count": sum(1 for o in overlaps if o["is_overlap_warning"]),
        "compartments": compartments,
        "true_multipart": [c["xb_id"] for c in compartments if c["is_true_multipart"]],
        "note": (
            "Rook=共边长度>1mm；Queen=共边或共点；重叠单独记录，仅>1.0 m² 标记为 WARNING。"
            "Rook 邻接=41 仅为本测试数据回归值，非通用质量规则。"
        ),
    }
    return report


def main():
    ap = argparse.ArgumentParser(
        description="森林小班拓扑校验（Rook/Queen 邻接、多部件、连通性、重叠）")
    ap.add_argument("--gpkg", required=True, help="forest_compartments.gpkg 路径")
    ap.add_argument("--layer", default="xiaoban_preliminary")
    ap.add_argument("--report", help="输出 JSON 报告路径（可选）")
    a = ap.parse_args()

    report = validate_topology(a.gpkg, a.layer)
    # Windows ArcGIS/GBK consoles cannot encode symbols such as m²; escaped
    # JSON keeps the report content identical while making stdout portable.
    text = json.dumps(report, ensure_ascii=True, indent=2)
    print(text)
    if a.report:
        Path(a.report).write_text(text, encoding="utf-8")
    # 退出码：存在重叠 WARNING 则非 0，便于 CI / 脚本判定
    raise SystemExit(2 if report["overlap_warning_count"] > 0 else 0)


if __name__ == "__main__":
    main()
