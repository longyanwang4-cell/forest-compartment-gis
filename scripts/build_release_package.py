#!/usr/bin/env python3
"""Build the audited Codex skill ZIP with a byte-accurate install manifest."""
from __future__ import annotations
import argparse, hashlib, json, zipfile
from pathlib import Path

EXCLUDE_NAMES = {"forest-compartment-gis-codex.zip", "OPEN_SOURCE_AUDIT.md", "STAGE2_OPEN_SOURCE_REPORT.md"}
EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "venv", "release-validation"}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    root, out = args.source.resolve(), args.output.resolve()
    files = []
    for p in root.rglob("*"):
        if not p.is_file() or p.is_symlink() or p.resolve() == out: continue
        rel = p.relative_to(root)
        if p.name in EXCLUDE_NAMES or p.name.endswith('.pyt.xml') or any(x in EXCLUDE_DIRS for x in rel.parts): continue
        if rel.name == "PACKAGE_SHA256SUMS.txt" or rel.name == ".release-package.json": continue
        files.append((rel.as_posix(), p))
    files.sort()
    entries = []
    for rel, p in files:
        entries.append((hashlib.sha256(p.read_bytes()).hexdigest(), rel))
    manifest = "".join(f"{h}  {rel}\n" for h, rel in entries)
    marker = json.dumps({"schema_version": "1", "package": "forest-compartment-gis", "manifest": "PACKAGE_SHA256SUMS.txt"}, ensure_ascii=False, indent=2) + "\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, p in files: z.write(p, rel)
        z.writestr("PACKAGE_SHA256SUMS.txt", manifest.encode())
        z.writestr(".release-package.json", marker.encode())
    print(f"built {out} ({len(files)} files)")
    return 0
if __name__ == "__main__": raise SystemExit(main())
