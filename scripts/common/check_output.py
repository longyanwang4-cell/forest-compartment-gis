"""Validate report directory before any write (standard library only)."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from forestgis_core.path_safety import ensure_disjoint_roots

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    _, output = ensure_disjoint_roots(args.input, args.output)
    output.mkdir(parents=True, exist_ok=True)
