"""收藏股票的進出場訊號檢查（四色用還原價，與 K 線頁完全一致）。
"""
from __future__ import annotations

import pandas as pd

from . import store
from .config import Settings
from .four_color import four_color
from .transform import adjust_prices, resample_ohlcv


def _entry_exit_points(colors: pd.Series) -> pd.DataFrame:
    """用持倉狀態機掃出買/賣點。回傳 DataFrame(index=date, action=buy/sell)。"""
    holding = False
    actions = []
    for d, c in colors.items():
        if not holding and c == "red":
            actions.append((d, "buy"))
            holding = True
        elif holding and c == "black":
            actions.append((d, "sell"))
            holding = False
    if not actions:
        return pd.DataFrame(columns=["action"]).rename_axis("date")
    return pd.DataFrame(actions, columns=["date", "action"]).set_index("date")


def check_favorites(bars: pd.DataFrame, instruments: pd.DataFrame,
                    favorites: list[str], settings: Settings | None = None,
                    as_of: pd.Timestamp | None = None) -> dict:
    """回傳收藏股票中，as_of 當日是「買入點/賣出點」的清單，及每檔目前部位狀態。

    還原方式與 K 線頁一致：load_bars -> adjust_prices -> resample(adjusted=True) -> four_color
    （不使用傳入的 bars 來算四色，改用單檔重讀，確保與 K 線頁同一條資料流。）
    """
    s = settings or Settings.load()
    name_map = dict(zip(instruments["stock_id"].astype(str), instruments["name"]))
    fc = s.four_color
    max_lb = max(fc.red_price_lookback, fc.red_vol_lookback,
                 fc.black_price_lookback, fc.black_vol_lookback)

    if as_of is None:
        as_of = pd.to_datetime(bars["date"]).max()
    as_of = pd.Timestamp(as_of).normalize()

    buy, sell, status = [], [], []
    for sid in favorites:
        raw = store.load_bars(sid, final_only=True)
        if raw.empty:
            continue

        # ★ 與 K 線頁完全相同的還原資料流
        daily = adjust_prices(raw, store.load_dividends(sid))
        g = resample_ohlcv(daily, "daily", adjusted=True)   # 還原價 → 四色
        g.index = pd.to_datetime(g.index).normalize()

        if len(g) < max_lb + 2 or as_of not in g.index:
            continue

        colors = four_color(g, fc)
        pts = _entry_exit_points(colors.loc[:as_of])

        cur_color = colors.loc[as_of]
        # 顯示用原始收盤（對照市價）：用未還原的 raw
        raw_idx = pd.to_datetime(raw["date"]).dt.normalize() if "date" in raw.columns else raw.index.normalize()
        try:
            disp_close = round(float(raw.set_index(raw_idx).loc[as_of, "close"]), 2) if "date" in raw.columns \
                else round(float(g.loc[as_of, "close"]), 2)
        except Exception:
            disp_close = round(float(g.loc[as_of, "close"]), 2)

        base = {"代號": sid, "名稱": name_map.get(sid, ""),
                "收盤": disp_close,
                "目前顏色": {"red": "紅", "yellow": "黃", "blue": "藍",
                            "black": "黑", "gray": "—"}.get(cur_color, cur_color)}

        if as_of in pts.index:
            act = pts.loc[as_of, "action"]
            if act == "buy":
                buy.append(base)
            elif act == "sell":
                sell.append(base)

        if len(pts):
            last_act = pts.iloc[-1]["action"]
            last_date = pts.index[-1]
            base2 = dict(base)
            base2["最近訊號"] = "買入" if last_act == "buy" else "賣出"
            base2["訊號日"] = last_date.date().isoformat()
            base2["目前部位"] = "持有中" if last_act == "buy" else "空手"
            status.append(base2)
        else:
            base2 = dict(base)
            base2["最近訊號"] = "—"
            base2["訊號日"] = "—"
            base2["目前部位"] = "空手（無訊號紀錄）"
            status.append(base2)

    buy_cols = ["代號", "名稱", "收盤", "目前顏色"]
    status_cols = ["代號", "名稱", "收盤", "目前顏色", "最近訊號", "訊號日", "目前部位"]
    return {
        "buy": pd.DataFrame(buy, columns=buy_cols),
        "sell": pd.DataFrame(sell, columns=buy_cols),
        "status": pd.DataFrame(status, columns=status_cols),
        "as_of": as_of,
    }