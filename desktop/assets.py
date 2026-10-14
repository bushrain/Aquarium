"""贴图资源加载：把透明背景 PNG 放入 desktop/assets/ 即可替换默认绘制。

支持的文件名（全部可选，缺哪个就回退到程序内置绘制）：
    fish.png         鱼的基础贴图（朝右），会被淡染成鱼群的各种配色
    fish_0.png ~ fish_5.png   指定配色的鱼贴图（提供则直接使用，不再淡染）
    corpse.png       死鱼贴图（默认已翻肚，程序只做旋转/朝向）
    food.png         鱼食颗粒（按颗粒大小缩放）
    plant.png        水草（底部为根，程序负责摇摆）
    bubble.png       气泡（按气泡大小缩放）
    net.png          渔网光标（热点取图像中心）
    feed_cursor.png  喂食光标（热点取图像中心）

替换文件后重启程序生效（本模块在启动时缓存）。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QPainter, QPixmap

ASSET_DIR = Path(__file__).resolve().parent / "assets"

_cache: dict[str, QPixmap | None] = {}
_tint_cache: dict[tuple, QPixmap] = {}


def get(name: str) -> QPixmap | None:
    """加载 assets/<name>.png，不存在或加载失败返回 None。"""
    if name not in _cache:
        path = ASSET_DIR / f"{name}.png"
        if path.exists():
            pm = QPixmap(str(path))
            _cache[name] = pm if not pm.isNull() else None
        else:
            _cache[name] = None
    return _cache[name]


def has(name: str) -> bool:
    return get(name) is not None


def tinted(name: str, color: tuple, strength: float = 0.32) -> QPixmap | None:
    """把贴图按颜色淡染（用于一张白色鱼贴图生成多种配色），结果带缓存。"""
    base = get(name)
    if base is None:
        return None
    key = (name, color, strength)
    if key not in _tint_cache:
        pm = base.copy()
        p = QPainter(pm)
        p.setCompositionMode(QPainter.CompositionMode_SourceAtop)
        p.fillRect(pm.rect(), QColor(*color, int(255 * strength)))
        p.end()
        _tint_cache[key] = pm
    return _tint_cache[key]
