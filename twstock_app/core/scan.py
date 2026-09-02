"""全選股池訊號掃描。

對選股池內每一檔跑四色判定，抓出「最新一根剛轉入紅(買進)或黑(賣出)」的股票。
只掃日線（訊號密度最合理）；週/月線訊號太稀疏，不適合每日掃描。

回傳兩張表：買進清單、賣出清單，各含 代號 / 名稱 / 收盤 / 成交量 / 成交金額 / 連續同色天數。
排序：依「成交金額（收盤×成交量）」由大到小 = 近似市值排序，權值股排前面。
"""
from __future__ import annotations

import pandas as pd

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

    # 暖機所需天數（紅黑六參數最大值）
    fc = s.four_color
    max_lb = max(fc.red_price_lookback, fc.red_vol_lookback,
                 fc.black_price_lookback, fc.black_vol_lookback)

    buy_rows, sell_rows = [], []

    for sid, g in bars.groupby("stock_id"):
        g = g.copy()
        g["date"] = pd.to_datetime(g["date"])
        g = g.set_index("date").sort_index()
        if len(g) < max_lb + 2:
            continue

        # 選股池：以 as_of 當日是否在池內為準（point-in-time）
        uni = in_universe(g, s.universe)
        if as_of not in g.index or not bool(uni.get(as_of, False)):
            continue

        colors = four_color(g, s.four_color)
        sig = signals(colors)
        if as_of not in sig.index:
            continue

        last = g.loc[as_of]
        # 連續同色天數（往回數還是同一色的根數）
        col_series = colors.loc[:as_of]
        cur = col_series.iloc[-1]
        streak = 1
        for c in col_series.iloc[:-1][::-1]:
            if c == cur: streak += 1
            else: break

        close_v = float(last["close"])
        vol_v = float(last["volume"])
        turnover = close_v * vol_v   # 成交金額（近似市值）
        row = {"代號": sid, "名稱": name_map.get(str(sid), ""),
               "收盤": round(close_v, 2),
               "成交量(張)": int(vol_v),
               "成交金額(千元)": int(turnover),   # 收盤(元)×量(張)≈千元為單位
               "連續天數": streak}
        if bool(sig.loc[as_of, "buy"]):
            buy_rows.append(row)
        elif bool(sig.loc[as_of, "sell"]):
            sell_rows.append(row)

    cols = ["代號", "名稱", "收盤", "成交量(張)", "成交金額(千元)", "連續天數"]
    # ★ 改為依成交金額（近似市值）由大到小排序
    buy = pd.DataFrame(buy_rows).sort_values("成交金額(千元)", ascending=False) if buy_rows else pd.DataFrame(columns=cols)
    sell = pd.DataFrame(sell_rows).sort_values("成交金額(千元)", ascending=False) if sell_rows else pd.DataFrame(columns=cols)
    return {"as_of": as_of, "buy": buy.reset_index(drop=True), "sell": sell.reset_index(drop=True)}