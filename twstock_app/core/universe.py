"""選股池：排除低價股與冷門股。逐日重算（point-in-time），避免前視偏差。"""
from __future__ import annotations

import pandas as pd

from .config import UniverseConfig


def in_universe(daily: pd.DataFrame, cfg: UniverseConfig) -> pd.Series:
    """回傳逐日的布林 Series：該日該股是否在選股池內。

    成交量用滾動中位數而非單日值 —— 單日量容易被一根爆量或一天無量誤判。
    """
    close_ok = daily["close"] >= cfg.min_close
    med_vol = daily["volume"].rolling(cfg.volume_window, min_periods=cfg.volume_window // 2).median()
    vol_ok = med_vol >= cfg.min_volume_lots
    seasoned = pd.Series(range(len(daily)), index=daily.index) >= cfg.min_listed_days
    return close_ok & vol_ok & seasoned