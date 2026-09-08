"""Filesystem safety helpers shared by the workflow, inspectors, and packagers.

The project treats teacher-provided input as read-only. These helpers enforce that
policy even when paths contain symlinks, junction-like indirections, or accidental
input/output overlap.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator


class PathSafetyError(ValueError):
    """A path violates the skill's read-only or containment policy."""


def assert_no_link_components(path: str | Path) -> Path:
    """Reject symlink/reparse points in every existing component of *path*.

    This matters for output paths too: an apparently new output directory may
    have a junction/symlink parent that redirects writes outside the intended
    location.
    """
    raw = Path(path).expanduser().absolute()
    parts = raw.parts
    if not parts:
        raise PathSafetyError("路径为空")
    current = Path(parts[0])
    for part in parts[1:]:
        current = current / part
        if not current.exists() and not current.is_symlink():
            continue
        if is_symlink_or_reparse(current):
            raise PathSafetyError(f"路径包含符号链接或重解析点: {current}")
    return raw


def resolved(path: str | Path) -> Path:
    assert_no_link_components(path)
    return Path(path).expanduser().resolve(strict=False)


def is_within(child: str | Path, parent: str | Path) -> bool:
    child_r = resolved(child)
    parent_r = resolved(parent)
    try:
        child_r.relative_to(parent_r)
        return True
    except ValueError:
        return False


def ensure_disjoint_roots(input_root: str | Path, output_root: str | Path) -> tuple[Path, Path]:
    """Reject equal or nested input/output roots in either direction."""
    inp = resolved(input_root)
    out = resolved(output_root)
    if inp == out:
        raise PathSafetyError("输入目录与输出目录不能相同")
    if is_within(out, inp):
        raise PathSafetyError("输出目录不能位于老师原始数据目录内部")
    if is_within(inp, out):
        raise PathSafetyError("输入目录不能位于输出目录内部")
    return inp, out


def ensure_output_outside_input(input_root: str | Path, output_path: str | Path) -> Path:
    inp = resolved(input_root)
    out = resolved(output_path)
    if out == inp or is_within(out, inp):
        raise PathSafetyError("输出文件不能写入老师原始数据目录")
    return out


def is_symlink_or_reparse(path: Path) -> bool:
    """Best-effort rejection of symlinks and Windows reparse points.

    Python exposes FILE_ATTRIBUTE_REPARSE_POINT through st_file_attributes on
    Windows. On other systems, is_symlink() covers the relevant case.
    """
    try:
        if path.is_symlink():
            return True
        st = path.lstat()
        attrs = getattr(st, "st_file_attributes", 0)
        reparse_flag = getattr(os.stat_result, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        # pathlib/stat do not expose the constant consistently; 0x400 is the
        # documented Windows FILE_ATTRIBUTE_REPARSE_POINT value.
        return bool(attrs & (reparse_flag or 0x400))
    except OSError:
        return True


def iter_safe_files(root: str | Path) -> Iterator[Path]:
    """Yield regular, non-link files contained by *root* without following links."""
    base = resolved(root)
    if is_symlink_or_reparse(Path(root).expanduser().absolute()):
        raise PathSafetyError(f"拒绝符号链接或重解析点根目录: {root}")
    if not base.exists() or not base.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        current = Path(dirpath)
        # Prune symlink/reparse directories before descent.
        dirnames[:] = [
            name
            for name in dirnames
            if not is_symlink_or_reparse(current / name)
        ]
        for name in filenames:
            p = current / name
            if is_symlink_or_reparse(p):
                continue
            try:
                rp = p.resolve(strict=True)
                rp.relative_to(base)
            except (OSError, ValueError):
                continue
            if rp.is_file():
                yield p


def assert_safe_regular_file(path: str | Path, root: str | Path) -> Path:
    p = Path(path)
    base = resolved(root)
    if is_symlink_or_reparse(p):
        raise PathSafetyError(f"拒绝符号链接或重解析点文件: {p}")
    try:
        rp = p.resolve(strict=True)
        rp.relative_to(base)
    except (OSError, ValueError) as exc:
        raise PathSafetyError(f"文件不在允许目录内: {p}") from exc
    if not rp.is_file():
        raise PathSafetyError(f"不是普通文件: {p}")
    return rp


def assert_safe_dataset_companions(path: str | Path, root: str | Path) -> None:
    """Validate sidecar files that GIS libraries may open implicitly.

    A safe `.shp` can still cause GDAL/ArcPy to read a linked `.dbf`, `.prj`, or
    `.shx`. Raster drivers may also read `.aux.xml`, `.ovr`, or world files.
    VRT is intentionally rejected because its XML can reference arbitrary local
    or remote datasets outside the teacher-data directory.
    """
    p = assert_safe_regular_file(path, root)
    base = resolved(root)
    suffix = p.suffix.lower()
    if suffix == ".vrt":
        raise PathSafetyError("出于安全考虑，当前版本不接受可引用外部数据源的VRT；请转换为本地GeoTIFF")
    candidates: list[Path] = []
    if suffix == ".shp":
        candidates.extend(p.parent.glob(p.stem + ".*"))
    elif suffix in {".tif", ".tiff", ".img", ".jp2"}:
        candidates.extend(Path(str(p) + ext) for ext in (".aux.xml", ".ovr", ".xml"))
        candidates.extend(p.with_suffix(ext) for ext in (".tfw", ".tifw", ".wld"))
    for companion in candidates:
        if not companion.exists() and not companion.is_symlink():
            continue
        assert_safe_regular_file(companion, base)
