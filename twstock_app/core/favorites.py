from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAV_PATH = ROOT / "config" / "favorites.json"


def load_favorites() -> list[str]:
    """回傳收藏的股票代號清單（保序）。檔案不存在回空清單。"""
    if not FAV_PATH.exists():
        return []
    try:
        data = json.loads(FAV_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_favorites(favs: list[str]) -> None:
    FAV_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 去重保序
    seen, out = set(), []
    for s in favs:
        s = str(s).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    FAV_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def add_favorite(stock_id: str) -> list[str]:
    favs = load_favorites()
    if stock_id not in favs:
        favs.append(stock_id)
        save_favorites(favs)
    return favs


def remove_favorite(stock_id: str) -> list[str]:
    favs = [s for s in load_favorites() if s != stock_id]
    save_favorites(favs)
    return favs