"""四色策略回測引擎（四色用還原價）。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import store
from .adjust_helper import adjust_all_bars
from .config import FourColorConfig
from .four_color import four_color


@dataclass
class BacktestConfig:
    initial_cash: float = 1_000_000
    position_pct: float = 0.01
    position_mode: str = "fixed"
    max_holdings: int = 20
    universe_size: int = 50
    universe_window: int = 60
    fee_rate: float = 0.001425
    tax_rate: float = 0.003
    min_price: float = 6.0
    benchmark_id: str = "0050"


@dataclass
class Trade:
    stock_id: str
    entry_date: pd.Timestamp
    entry_price: float
    exit_date: pd.Timestamp | None = None
    exit_price: float | None = None
    shares: float = 0
    pnl: float = 0.0
    ret: float = 0.0


def _auto_adjust(df: pd.DataFrame, jump_threshold: float = 0.35) -> pd.DataFrame:
    """備援：偵測分割/大除息跳空還原（除權息資料缺時用）。"""
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


def _build_panel(bars: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """把長表拆成 {stock_id: 還原價日線df(index=date)}。

    先用除權息還原（adjust_all_bars）；若某檔無除權息資料，
    再套 _auto_adjust 當備援（抓大跳空）。
    """
    div = store.load_all_dividends()
    adj = adjust_all_bars(bars, div)   # 除權息還原（有資料的檔）

    # 哪些股票有除權息資料（已被精確還原），其餘用備援
    has_div = set(div["stock_id"].astype(str).unique()) if not div.empty else set()

    out = {}
    for sid, g in adj.groupby("stock_id"):
        g = g.copy()
        g["date"] = pd.to_datetime(g["date"])
        g = g.set_index("date").sort_index()
        if str(sid) not in has_div:
            g = _auto_adjust(g)   # 沒除權息資料 → 備援還原
        out[str(sid)] = g
    return out


def run_backtest(bars: pd.DataFrame, bt: BacktestConfig,
                 fc: FourColorConfig | None = None,
                 start: str | None = None, end: str | None = None) -> dict:
    fc = fc or FourColorConfig()
    panel = _build_panel(bars)

    all_dates = pd.to_datetime(sorted(bars["date"].unique()))
    if start:
        all_dates = all_dates[all_dates >= pd.Timestamp(start)]
    if end:
        all_dates = all_dates[all_dates <= pd.Timestamp(end)]

    max_lb = max(fc.red_price_lookback, fc.red_vol_lookback,
                 fc.black_price_lookback, fc.black_vol_lookback)

    colors, turnover = {}, {}
    for sid, df in panel.items():
        if len(df) < max_lb + 2:
            continue
        colors[sid] = four_color(df, fc)
        turnover[sid] = (df["close"] * df["volume"]).rolling(
            bt.universe_window, min_periods=bt.universe_window // 2).mean()

    cash = bt.initial_cash
    if bt.position_mode == "rotate":
        per_trade = bt.initial_cash / bt.max_holdings
        slot_limit = bt.max_holdings
    else:
        per_trade = bt.initial_cash * bt.position_pct
        slot_limit = None
    holdings: dict[str, Trade] = {}
    closed: list[Trade] = []
    equity_curve = []
    pending_buys, pending_sells = [], []

    for i, d in enumerate(all_dates):
        for sid in pending_sells:
            if sid in holdings and d in panel[sid].index:
                px = float(panel[sid].loc[d, "open"])
                t = holdings.pop(sid)
                proceeds = t.shares * px * (1 - bt.fee_rate - bt.tax_rate)
                t.exit_date, t.exit_price = d, px
                cost = t.shares * t.entry_price * (1 + bt.fee_rate)
                t.pnl = proceeds - cost
                t.ret = t.pnl / cost if cost else 0
                cash += proceeds
                closed.append(t)
        for sid in pending_buys:
            if slot_limit is not None and len(holdings) >= slot_limit:
                break
            if sid not in holdings and d in panel[sid].index and cash >= per_trade:
                px = float(panel[sid].loc[d, "open"])
                if px <= 0:
                    continue
                shares = per_trade / (px * (1 + bt.fee_rate))
                holdings[sid] = Trade(sid, d, px, shares=shares)
                cash -= per_trade
        pending_buys, pending_sells = [], []

        tvals = []
        for sid, tv in turnover.items():
            if d in tv.index and not np.isnan(tv.loc[d]):
                px = panel[sid].loc[d, "close"]
                if px >= bt.min_price:
                    tvals.append((sid, tv.loc[d]))
        universe = set(s for s, _ in sorted(tvals, key=lambda x: -x[1])[:bt.universe_size])

        for sid in list(colors.keys()):
            c = colors[sid]
            if d not in c.index:
                continue
            pos = c.index.get_loc(d)
            if pos == 0:
                continue
            cur, prev = c.iloc[pos], c.iloc[pos - 1]
            if sid in holdings and cur == "black" and prev != "black":
                pending_sells.append(sid)
            elif sid not in holdings and sid in universe and cur == "red" and prev != "red":
                pending_buys.append(sid)

        mv = 0.0
        for sid, t in holdings.items():
            if d in panel[sid].index:
                mv += t.shares * float(panel[sid].loc[d, "close"])
        equity_curve.append((d, cash + mv))

    eq = pd.Series(dict(equity_curve)).sort_index()

    bench = None
    if bt.benchmark_id in panel:
        b = panel[bt.benchmark_id]
        b = b[(b.index >= all_dates[0]) & (b.index <= all_dates[-1])]
        if not b.empty:
            bench = bt.initial_cash * (b["close"] / b["close"].iloc[0])

    return {
        "equity": eq,
        "benchmark": bench,
        "trades": closed,
        "final_equity": float(eq.iloc[-1]) if len(eq) else bt.initial_cash,
        "config": bt,
    }


def summarize(result: dict) -> dict:
    eq = result["equity"]
    bt = result["config"]
    trades = result["trades"]
    if len(eq) < 2:
        return {}

    total_ret = eq.iloc[-1] / bt.initial_cash - 1
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / bt.initial_cash) ** (1 / years) - 1 if years > 0 else 0
    daily = eq.pct_change().dropna()
    sharpe = (daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else 0
    cummax = eq.cummax()
    mdd = ((eq - cummax) / cummax).min()

    wins = [t for t in trades if t.pnl > 0]
    win_rate = len(wins) / len(trades) if trades else 0
    avg_win = np.mean([t.ret for t in wins]) if wins else 0
    losses = [t for t in trades if t.pnl <= 0]
    avg_loss = np.mean([t.ret for t in losses]) if losses else 0

    out = {
        "總報酬": f"{total_ret:.1%}",
        "年化報酬(CAGR)": f"{cagr:.1%}",
        "夏普值": f"{sharpe:.2f}",
        "最大回撤": f"{mdd:.1%}",
        "交易次數": len(trades),
        "勝率": f"{win_rate:.1%}",
        "平均獲利": f"{avg_win:.1%}",
        "平均虧損": f"{avg_loss:.1%}",
    }
    if result["benchmark"] is not None:
        b = result["benchmark"]
        bench_ret = b.iloc[-1] / b.iloc[0] - 1
        out["0050報酬"] = f"{bench_ret:.1%}"
        out["超額報酬"] = f"{total_ret - bench_ret:.1%}"
    return out