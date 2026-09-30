"""全市場還原工具：把長表 bars 一次全部還原成還原價（四色判斷用）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def adjust_all_bars(bars: pd.DataFrame, dividends: pd.DataFrame) -> pd.DataFrame:
    """把全市場長表的 OHLC 換成還原價（原地覆蓋 open/high/low/close）。

    bars      : 長表，欄位 stock_id, date, open/high/low/close/volume...
    dividends : 全市場除權息，欄位 stock_id, date(除息交易日), cash_dividend, stock_dividend

    還原因子（與 transform.adjust_prices 相同）：
        f = (prev_close - cash) / (prev_close * (1 + stock))
    除息日「之前」的價格往前累乘 f。
    """
    if bars.empty:
        return bars
    df = bars.copy()
    df["date"] = pd.to_datetime(df["date"])

    if dividends is None or dividends.empty:
        return df   # 沒除權息資料，原樣返回（等於沒還原）

    div = dividends.copy()
    div["date"] = pd.to_datetime(div["date"])
    # 按股票分組除權息，加速查找
    div_by_sid = {sid: g.sort_values("date") for sid, g in div.groupby("stock_id")}

    out_parts = []
    for sid, g in df.groupby("stock_id"):
        g = g.sort_values("date").reset_index(drop=True)
        divs = div_by_sid.get(str(sid))
        if divs is None or divs.empty:
            out_parts.append(g)
            continue

        factor = np.ones(len(g))
        dates = g["date"].values
        closes = g["close"].values
        for _, row in divs.iterrows():
            ex_date = row["date"]
            # 找除息日在這檔資料中的位置
            pos_arr = np.where(dates == np.datetime64(ex_date))[0]
            if len(pos_arr) == 0:
                continue
            pos = int(pos_arr[0])
            if pos == 0:
                continue
            prev_close = float(closes[pos - 1])
            cash = float(row.get("cash_dividend", 0) or 0)
            stock = float(row.get("stock_dividend", 0) or 0)
            denom = prev_close * (1 + stock)
            if denom <= 0:
                continue
            f = (prev_close - cash) / denom
            factor[:pos] *= f

        for col in ("open", "high", "low", "close"):
            if col in g.columns:
                g[col] = (g[col].values * factor).round(4)
        out_parts.append(g)

    return pd.concat(out_parts, ignore_index=True)