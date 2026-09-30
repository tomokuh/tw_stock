"""全選股池訊號掃描（四色一律用還原價）。

對選股池內每一檔跑四色判定，抓出「最新一根剛轉入紅(買進)或黑(賣出)」的股票。
只掃日線。回傳買進/賣出清單，依成交金額（近似市值）排序。

★ 還原：掃描前先用除權息把全市場還原成還原價，四色吃還原價，
  除權息日不再誤判跳空。與 K 線頁、回測頁一致。
"""
from __future__ import annotations

import pandas as pd

from . import store
from .adjust_helper import adjust_all_bars
from .config import Settings
from .four_color import four_color, signals
from .universe import in_universe


def scan_signals(bars: pd.DataFrame, instruments: pd.DataFrame,
                 settings: Settings | None = None,
                 as_of: pd.Timestamp | None = None) -> dict[str, pd.DataFrame]:
    """bars: 全市場長表(stock_id,date,open,high,low,close,volume)。
    as_of: 掃描哪一天的訊號，預設用資料中最新日期。
    """
    s = settings or Settings.load()
    name_map = dict(zip(instruments["stock_id"].astype(str), instruments["name"]))

    if as_of is None:
        as_of = pd.to_datetime(bars["date"]).max()
    as_of = pd.Timestamp(as_of)

    # ★ 全市場一次還原（四色吃還原價）；顯示用的收盤另存原始價
    div = store.load_all_dividends()
    adj_bars = adjust_all_bars(bars, div)

    # 原始收盤（顯示用，讓清單顯示真實市價而非還原價）
    raw_close = {}
    for sid, g in bars.groupby("stock_id"):
        gg = g.copy()
        gg["date"] = pd.to_datetime(gg["date"])
        gg = gg.set_index("date")
        raw_close[str(sid)] = gg["close"]

    fc = s.four_color
    max_lb = max(fc.red_price_lookback, fc.red_vol_lookback,
                 fc.black_price_lookback, fc.black_vol_lookback)

    buy_rows, sell_rows = [], []

    for sid, g in adj_bars.groupby("stock_id"):
        g = g.copy()
        g["date"] = pd.to_datetime(g["date"])
        g = g.set_index("date").sort_index()
        if len(g) < max_lb + 2:
            continue

        uni = in_universe(g, s.universe)
        if as_of not in g.index or not bool(uni.get(as_of, False)):
            continue

        colors = four_color(g, s.four_color)   # 吃還原價
        sig = signals(colors)
        if as_of not in sig.index:
            continue

        col_series = colors.loc[:as_of]
        cur = col_series.iloc[-1]
        streak = 1
        for c in col_series.iloc[:-1][::-1]:
            if c == cur: streak += 1
            else: break

        # 顯示用收盤：原始市價（不是還原價）
        rc = raw_close.get(str(sid))
        disp_close = float(rc.loc[as_of]) if rc is not None and as_of in rc.index else float(g.loc[as_of, "close"])
        vol_v = float(g.loc[as_of, "volume"])
        turnover = disp_close * vol_v
        row = {"代號": sid, "名稱": name_map.get(str(sid), ""),
               "收盤": round(disp_close, 2),
               "成交量(張)": int(vol_v),
               "成交金額(千元)": int(turnover),
               "連續天數": streak}
        if bool(sig.loc[as_of, "buy"]):
            buy_rows.append(row)
        elif bool(sig.loc[as_of, "sell"]):
            sell_rows.append(row)

    cols = ["代號", "名稱", "收盤", "成交量(張)", "成交金額(千元)", "連續天數"]
    buy = pd.DataFrame(buy_rows).sort_values("成交金額(千元)", ascending=False) if buy_rows else pd.DataFrame(columns=cols)
    sell = pd.DataFrame(sell_rows).sort_values("成交金額(千元)", ascending=False) if sell_rows else pd.DataFrame(columns=cols)
    return {"as_of": as_of, "buy": buy.reset_index(drop=True), "sell": sell.reset_index(drop=True)}