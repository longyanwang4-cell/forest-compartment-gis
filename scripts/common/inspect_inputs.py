#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from forestgis_core.path_safety import (  # noqa: E402
    PathSafetyError,
    assert_no_link_components,
    assert_safe_dataset_companions,
    ensure_output_outside_input,
    is_symlink_or_reparse,
    iter_safe_files,
)

RASTER = {'.tif', '.tiff', '.img', '.jp2', '.vrt'}
VECTOR = {'.shp', '.gpkg', '.geojson', '.json', '.kml', '.kmz'}
TRACK = {'.gpx', '.kml', '.kmz', '.geojson', '.json'}


def kind(p: Path) -> str:
    n = p.name.lower()
    e = p.suffix.lower()
    if e in RASTER:
        return 'dem' if any(x in n for x in ['dem', 'dtm', 'elev', '高程']) else 'imagery'
    if e in VECTOR:
        if any(x in n for x in ['bound', 'boundary', '范围', '边界']):
            return 'boundary'
        if any(x in n for x in ['xiaoban', 'compartment', '小班']):
            return 'compartment'
        if e in TRACK and any(x in n for x in ['track', 'route', '轨迹', '线路', '两步路']):
            return 'track'
        return 'vector'
    if e in TRACK:
        return 'track'
    return 'other'


def raster_info(p: Path) -> dict:
    try:
        import rasterio
        with rasterio.open(p) as d:
            return {
                'crs': str(d.crs),
                'width': d.width,
                'height': d.height,
                'bands': d.count,
                'resolution': list(d.res),
                'bounds': list(d.bounds),
                'nodata': d.nodata,
            }
    except Exception as exc:
        return {'inspection_error': str(exc)}


def vector_info(p: Path) -> dict:
    """Read OGR/Fiona metadata without loading the full vector dataset into RAM."""
    try:
        import fiona
        with fiona.open(p) as src:
            geometry = (src.schema or {}).get('geometry')
            properties = list(((src.schema or {}).get('properties') or {}).keys())
            crs = src.crs_wkt or str(src.crs)
            return {
                'crs': str(crs) if crs else None,
                'features': len(src),
                'geometry_types': [str(geometry)] if geometry else [],
                'bounds': [float(x) for x in src.bounds],
                'fields': properties,
                'inspection_mode': 'metadata_only',
            }
    except Exception as exc:
        return {'inspection_error': str(exc), 'inspection_mode': 'metadata_only'}


def count_skipped_links(root: Path) -> int:
    count = 0
    for p in root.rglob('*'):
        if is_symlink_or_reparse(p):
            count += 1
    return count


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--output')
    ap.add_argument('--max-files', type=int, default=10000, help='输入目录最大安全扫描文件数')
    args = ap.parse_args()
    try:
        assert_no_link_components(args.root)
        if args.output:
            assert_no_link_components(args.output)
    except PathSafetyError as exc:
        raise SystemExit(str(exc)) from exc
    root = Path(args.root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise SystemExit('目录不存在或不是文件夹: ' + str(root))

    output: Path | None = None
    if args.output:
        try:
            output = ensure_output_outside_input(root, args.output)
        except PathSafetyError as exc:
            raise SystemExit(str(exc)) from exc

    if args.max_files < 1:
        raise SystemExit('--max-files必须大于0')
    files = []
    security_rejections = []
    scanned_files = 0
    for p in iter_safe_files(root):
        scanned_files += 1
        if scanned_files > args.max_files:
            raise SystemExit(f'输入目录文件数超过安全上限 {args.max_files}，已停止扫描；请缩小输入目录或显式提高 --max-files')
        k = kind(p)
        if k == 'other':
            continue
        try:
            assert_safe_dataset_companions(p, root)
        except PathSafetyError as exc:
            security_rejections.append({'relative_path': p.relative_to(root).as_posix(), 'reason': str(exc)})
            continue
        r = {
            'path': str(p.resolve()),
            'relative_path': p.relative_to(root).as_posix(),
            'kind': k,
            'size_bytes': p.stat().st_size,
        }
        if p.suffix.lower() in RASTER:
            r.update(raster_info(p))
        elif p.suffix.lower() in VECTOR:
            r.update(vector_info(p))
        files.append(r)

    summary = {
        k: sum(x['kind'] == k for x in files)
        for k in ['imagery', 'dem', 'boundary', 'compartment', 'track', 'vector']
    }
    warnings = []
    if not summary['imagery']:
        warnings.append('未识别到主影像')
    if not summary['boundary']:
        warnings.append('未识别到作业边界')
    if not summary['dem']:
        warnings.append('未识别到DEM，可继续但无地形约束')
    skipped_links = count_skipped_links(root)
    if skipped_links:
        warnings.append(f'为防止读取输入目录外的数据，已跳过 {skipped_links} 个符号链接或重解析点')
    if security_rejections:
        warnings.append(f'为防止GIS驱动隐式读取外部文件，已拒绝 {len(security_rejections)} 个不安全数据集')

    out = {
        'root': str(root),
        'summary': summary,
        'files': files,
        'warnings': warnings,
        'security': {
            'skipped_symlink_or_reparse_count': skipped_links,
            'rejected_dataset_count': len(security_rejections),
            'rejected_datasets': security_rejections,
            'scanned_file_count': scanned_files,
            'max_files': args.max_files,
        },
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    print(text)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
