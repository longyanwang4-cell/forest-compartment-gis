"""Execution-mode and human-oversight policy for the practice workflow."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


class PolicyError(ValueError):
    pass


_MODE_DEFAULTS: dict[str, dict[str, Any]] = {
    "fast": {
        "provenance": {"hash_mode": "quick"},
        "human_oversight": {"review_candidate_before_build": False},
        "reporting": {"html_summary": True, "field_kit": True},
    },
    "standard": {
        "provenance": {"hash_mode": "sampled"},
        "human_oversight": {"review_candidate_before_build": False},
        "reporting": {"html_summary": True, "field_kit": True},
    },
    "strict": {
        "provenance": {"hash_mode": "full"},
        "human_oversight": {"review_candidate_before_build": True},
        "reporting": {"html_summary": True, "field_kit": True},
        "validation": {
            "overlap_tolerance_m2": 0.0,
            "gap_tolerance_m2": 1.0,
            "outside_tolerance_m2": 0.0,
            "min_coverage_ratio": 0.9995,
            "require_projected_crs": True,
            "require_meter_unit": True,
        },
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def apply_execution_mode(config: dict[str, Any], mode: str | None) -> dict[str, Any]:
    normalized = str(mode or config.get("execution_mode") or "standard").strip().lower()
    if normalized not in _MODE_DEFAULTS:
        raise PolicyError(f"不支持的execution_mode: {normalized}")
    # 用户显式配置优先于模式默认值。
    merged = _deep_merge(_MODE_DEFAULTS[normalized], config)
    merged["execution_mode"] = normalized
    return merged


def requires_candidate_review(config: dict[str, Any]) -> bool:
    return bool((config.get("human_oversight") or {}).get("review_candidate_before_build", False))
