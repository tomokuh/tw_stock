"""四色 K 線狀態機（紅、黑條件各自獨立）。

紅（買進訊號）：
    收盤 ≥ 前 red_price_lookback 日最高收盤（創新高）
    且 量 > 前 red_vol_lookback 日「平均量」× red_vol_ratio

黑（賣出訊號）：
    收盤 ≤ 前 black_price_lookback 日最低收盤（創新低）
    且 量 > 前 black_vol_lookback 日「平均量」× black_vol_ratio

（紅、黑六個參數完全獨立；量能基準為「平均量」，不含今日）

顏色規則（紅/黑是「訊號色」，每一根都必須重新滿足條件，不會黏著）:
    紅 : red_px  and red_vol_ok
    黑 : black_px and black_vol_ok
    前一日 紅 : black_px -> 藍 ; red_px -> 黃 ; 灰色地帶 -> 黃
    前一日 黑 : red_px   -> 黃 ; black_px -> 藍 ; 灰色地帶 -> 藍
    前一日 黃 : black_px -> 藍 ; 否則 -> 維持 黃
    前一日 藍 : red_px   -> 黃 ; 否則 -> 維持 藍
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import FourColorConfig


def four_color(df: pd.DataFrame, cfg: FourColorConfig) -> pd.Series:
    """回傳與 df 等長的顏色 Series: red/yellow/blue/black/gray(暖機)。"""
    close = df["close"].astype(float)
    volume = df["volume"].astype(float)

    # === 紅：價格創 red_price_lookback 日新高 + 量 > 前 red_vol_lookback 日均量 × ratio ===
    red_prev_high = close.shift(1).rolling(cfg.red_price_lookback).max()
    red_px = (close >= red_prev_high).to_numpy()
    red_avg_vol = volume.shift(1).rolling(cfg.red_vol_lookback).mean()
    red_vol_ok = (volume > red_avg_vol * cfg.red_vol_ratio).to_numpy()

    # === 黑：價格創 black_price_lookback 日新低 + 量 > 前 black_vol_lookback 日均量 × ratio ===
    black_prev_low = close.shift(1).rolling(cfg.black_price_lookback).min()
    black_px = (close <= black_prev_low).to_numpy()
    black_avg_vol = volume.shift(1).rolling(cfg.black_vol_lookback).mean()
    black_vol_ok = (volume > black_avg_vol * cfg.black_vol_ratio).to_numpy()

    # 暖機：任一 rolling 尚未成形前都算暖機（取最大回看天數）
    max_lb = max(cfg.red_price_lookback, cfg.red_vol_lookback,
                 cfg.black_price_lookback, cfg.black_vol_lookback)
    warmup = (pd.Series(range(len(df))).values < max_lb)

    n = len(df)
    out = np.empty(n, dtype=object)
    prev = cfg.initial_color

    for i in range(n):
        if warmup[i]:
            out[i] = "gray"
            continue

        r, rv = bool(red_px[i]), bool(red_vol_ok[i])
        b, bv = bool(black_px[i]), bool(black_vol_ok[i])

        if r and rv:
            c = "red"                        # 創新高 + 紅量過關 -> 買進
        elif b and bv:
            c = "black"                      # 創新低 + 黑量過關 -> 賣出
        elif prev == "red":
            c = "blue" if b else "yellow"    # 紅未續紅 -> 降級
        elif prev == "black":
            c = "yellow" if r else "blue"    # 黑未續黑 -> 降級
        elif prev == "yellow":
            c = "blue" if b else "yellow"
        elif prev == "blue":
            c = "yellow" if r else "blue"
        elif cfg.persist_on_undefined:
            c = prev
        else:
            c = "blue" if b else "yellow"

        out[i] = c
        prev = c

    return pd.Series(out, index=df.index, name="color")


def signals(colors: pd.Series) -> pd.DataFrame:
    """僅在「轉入」紅/黑的那一根觸發，連續紅不重複發訊。"""
    prev = colors.shift(1)
    return pd.DataFrame(
        {
            "buy": (colors == "red") & (prev != "red"),
            "sell": (colors == "black") & (prev != "black"),
        },
        index=colors.index,
    )