"""單一標的回測：四色訊號進出（全押）vs 買進持有同一檔。

策略：
  進場 = 四色首次轉紅（前一根非紅）→ 隔日開盤「全押」買入
  出場 = 轉黑 → 隔日開盤全部賣出，回到現金
  空手期間 = 純現金，等下一個紅訊號
  成本 = 買賣手續費 + 賣出證交稅
對照 = 同一檔買進持有（buy and hold），一樣用還原價。

★ 還原：優先用除權息（store 的 dividends）精確還原；若無除權息資料，
  退回 _auto_adjust（偵測大跳空）。四色與買賣都用還原價。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import store
from .config import FourColorConfig
from .four_color import four_color


@dataclass
class SingleBTConfig:
    initial_cash: float = 1_000_000
    fee_rate: float = 0.001425
    tax_rate: float = 0.003


def _auto_adjust(df: pd.DataFrame, jump_threshold: float = 0.35) -> pd.DataFrame:
    """備援：偵測分割/大除息跳空還原（無除權息資料時用）。"""
    df = df.sort_index().copy()
    close = df["close"].values
    factor = np.ones(len(df))
    for i in range(len(df) - 1, 0, -1):
        prev, cur = close[i - 1], close[i]
        if prev > 0 and cur > 0:
            ratio = cur / prev
            if ratio < (1 - jump_threshold) or ratio > 1.5:
                factor[:i] *= ratio
    for col in ("open", "high", "low", "close"):
        if col in df:
            df[col] = df[col].values * factor
    return df


def _adjust_by_dividends(df: pd.DataFrame, dividends: pd.DataFrame) -> pd.DataFrame:
    """用除權息精確還原（與 transform.adjust_prices 同公式）。df index=date。"""
    df = df.sort_index().copy()
    if dividends is None or dividends.empty:
        return None   # 無除權息資料，交由呼叫端退回備援
    div = dividends.copy()
    div["date"] = pd.to_datetime(div["date"])
    div = div.set_index("date").sort_index()

    factor = np.ones(len(df))
    closes = df["close"].values
    for ex_date, row in div.iterrows():
        pos_arr = np.where(df.index.values == np.datetime64(ex_date))[0]
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
        if col in df:
            df[col] = (df[col].values * factor).round(4)
    return df


def run_single(daily: pd.DataFrame, cfg: SingleBTConfig,
               fc: FourColorConfig | None = None,
               start: str | None = None, end: str | None = None,
               adjust: bool = True, stock_id: str | None = None) -> dict:
    """daily: 單一標的日線（index=date，欄位 open/high/low/close/volume[/stock_id]）。
    stock_id: 若給，用它查除權息精確還原；否則從 daily 的 stock_id 欄取。
    """
    fc = fc or FourColorConfig()
    df = daily.copy()
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    # 取得 stock_id（優先參數，其次資料欄）
    sid = stock_id
    if sid is None and "stock_id" in df.columns and len(df):
        sid = str(df["stock_id"].iloc[0])

    if adjust:
        adj = None
        if sid is not None:
            adj = _adjust_by_dividends(df, store.load_dividends(sid))
        if adj is not None:
            df = adj          # 除權息精確還原
        else:
            df = _auto_adjust(df)   # 備援

    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]

    _max_lb = max(fc.red_price_lookback, fc.red_vol_lookback,
                  fc.black_price_lookback, fc.black_vol_lookback)
    if len(df) < _max_lb + 3:
        return {}

    colors = four_color(df, fc)
    prev_c = colors.shift(1)
    buy_sig = (colors == "red") & (prev_c != "red")
    sell_sig = (colors == "black") & (prev_c != "black")

    dates = df.index
    opens = df["open"].values
    closes = df["close"].values

    cash = cfg.initial_cash
    shares = 0.0
    in_pos = False
    entry_px = 0.0
    equity = []
    trades = []
    pending = None

    for i in range(len(df)):
        if pending == "buy" and not in_pos:
            px = opens[i]
            if px > 0:
                shares = cash / (px * (1 + cfg.fee_rate))
                entry_px = px
                cash = 0.0
                in_pos = True
                trades.append({"進場日": dates[i], "進場價": px})
        elif pending == "sell" and in_pos:
            px = opens[i]
            proceeds = shares * px * (1 - cfg.fee_rate - cfg.tax_rate)
            cost = shares * entry_px * (1 + cfg.fee_rate)
            trades[-1].update({"出場日": dates[i], "出場價": px,
                               "報酬": proceeds / cost - 1})
            cash = proceeds
            shares = 0.0
            in_pos = False
        pending = None

        if not in_pos and buy_sig.iloc[i]:
            pending = "buy"
        elif in_pos and sell_sig.iloc[i]:
            pending = "sell"

        equity.append(cash + shares * closes[i])

    eq = pd.Series(equity, index=dates)
    bh_shares = cfg.initial_cash / (closes[0] * (1 + cfg.fee_rate))
    bh = pd.Series(bh_shares * closes, index=dates)

    return {"equity": eq, "benchmark": bh, "trades": trades, "config": cfg}


def summarize_single(result: dict) -> dict:
    if not result:
        return {}
    eq = result["equity"]
    bh = result["benchmark"]
    trades = [t for t in result["trades"] if "報酬" in t]
    init = result["config"].initial_cash

    total = eq.iloc[-1] / init - 1
    bh_total = bh.iloc[-1] / init - 1
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / init) ** (1 / years) - 1 if years > 0 else 0
    daily_ret = eq.pct_change().dropna()
    sharpe = (daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0
    mdd = ((eq - eq.cummax()) / eq.cummax()).min()
    bh_mdd = ((bh - bh.cummax()) / bh.cummax()).min()
    wins = [t for t in trades if t["報酬"] > 0]

    return {
        "策略總報酬": f"{total:.1%}",
        "買進持有報酬": f"{bh_total:.1%}",
        "超額報酬": f"{total - bh_total:.1%}",
        "年化報酬": f"{cagr:.1%}",
        "夏普值": f"{sharpe:.2f}",
        "策略最大回撤": f"{mdd:.1%}",
        "持有最大回撤": f"{bh_mdd:.1%}",
        "交易次數": len(trades),
        "勝率": f"{len(wins)/len(trades):.1%}" if trades else "—",
    }