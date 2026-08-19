"""還原權值、週/月重取樣、移動平均。

順序不可顛倒：一定是「先在日線上還原 → 再 resample 成週/月」。
反過來做（先 resample 再還原）會在跨週的除權息日上算錯。
"""
from __future__ import annotations

import pandas as pd

FREQ_MAP = {"daily": None, "weekly": "W-FRI", "monthly": "ME"}


def adjust_prices(daily: pd.DataFrame, dividends: pd.DataFrame) -> pd.DataFrame:
    """回傳含還原後 OHLC 的日線。

    daily     : index=date, 欄位 open/high/low/close/volume
    dividends : 欄位 date(除權息交易日), cash_dividend, stock_dividend(每股配股數)

    調整因子（往前累乘）:
        f = (prev_close - cash) / (prev_close * (1 + stock_ratio))
    成交量不做還原（配股會膨脹股數，但成交量本身無需回溯調整）。
    """
    df = daily.sort_index().copy()
    factor = pd.Series(1.0, index=df.index)

    if dividends is not None and not dividends.empty:
        div = dividends.copy()
        div["date"] = pd.to_datetime(div["date"])
        div = div.set_index("date").sort_index()

        for ex_date, row in div.iterrows():
            if ex_date not in df.index:
                continue
            pos = df.index.get_loc(ex_date)
            if pos == 0:
                continue
            prev_close = float(df["close"].iloc[pos - 1])
            cash = float(row.get("cash_dividend", 0) or 0)
            stock = float(row.get("stock_dividend", 0) or 0)
            denom = prev_close * (1 + stock)
            if denom <= 0:
                continue
            f = (prev_close - cash) / denom
            # 除權息日「之前」的所有價格乘上 f
            factor.iloc[:pos] *= f

    out = df.copy()
    for col in ("open", "high", "low", "close"):
        out[f"{col}_adj"] = (df[col] * factor).round(4)
    out["adj_factor"] = factor
    return out


def resample_ohlcv(daily: pd.DataFrame, freq: str, adjusted: bool) -> pd.DataFrame:
    """把日線轉成 daily / weekly / monthly，並選擇原始或還原價。"""
    suffix = "_adj" if adjusted else ""
    cols = {
        "open": f"open{suffix}",
        "high": f"high{suffix}",
        "low": f"low{suffix}",
        "close": f"close{suffix}",
    }
    df = pd.DataFrame(
        {k: daily[v] for k, v in cols.items()} | {"volume": daily["volume"]},
        index=daily.index,
    )

    rule = FREQ_MAP[freq]
    if rule is None:
        return df

    out = df.resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return out.dropna(subset=["close"])


def add_ma(df: pd.DataFrame, price_windows: list[int], vol_windows: list[int]) -> pd.DataFrame:
    out = df.copy()
    for w in price_windows:
        out[f"ma{w}"] = df["close"].rolling(w).mean()
    for w in vol_windows:
        out[f"vma{w}"] = df["volume"].rolling(w).mean()
    return out