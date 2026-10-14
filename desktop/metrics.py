"""水质指标换算小工具（桌面端共享）。"""
from __future__ import annotations


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def pollution_of(state: dict) -> float:
    """综合污染度 0（清澈）~ 1（严重污染）。

    与后台的水质指标对应：
    - 氨氮 / 亚硝酸盐 超过 0.5 mg/L 属于危险
    - 硝酸盐 超过 60 mg/L 开始明显发绿
    - 有机废物 waste 超过 8 开始明显浑浊
    """
    ammonia = float(state.get("ammonia", 0) or 0)
    nitrite = float(state.get("nitrite", 0) or 0)
    nitrate = float(state.get("nitrate", 0) or 0)
    waste = float(state.get("waste", 0) or 0)
    p = (
        0.40 * clamp(ammonia / 0.5, 0.0, 1.0)
        + 0.20 * clamp(nitrite / 0.5, 0.0, 1.0)
        + 0.25 * clamp(nitrate / 60.0, 0.0, 1.0)
        + 0.15 * clamp(waste / 8.0, 0.0, 1.0)
    )
    return clamp(p, 0.0, 1.0)


def clarity_of(state: dict) -> float:
    """清澈度 0~1（1 为最清澈）。"""
    return 1.0 - pollution_of(state)


def clarity_label(clarity: float) -> str:
    if clarity >= 0.8:
        return "清澈"
    if clarity >= 0.6:
        return "微浊"
    if clarity >= 0.35:
        return "浑浊"
    return "严重浑浊"


def clarity_color(clarity: float) -> str:
    if clarity >= 0.8:
        return "#7ee8b2"
    if clarity >= 0.6:
        return "#d8e87e"
    if clarity >= 0.35:
        return "#f5c06a"
    return "#f38ba0"


def health_color(health: int) -> str:
    if health >= 70:
        return "#7ee8b2"
    if health >= 40:
        return "#f5c06a"
    return "#f38ba0"
