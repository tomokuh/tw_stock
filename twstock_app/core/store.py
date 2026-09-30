"""Parquet 儲存層。upsert key = (stock_id, date)，重跑不會產生重複列。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import DATA_DIR

BARS = DATA_DIR / "bars.parquet"
DIVIDENDS = DATA_DIR / "dividends.parquet"
INSTRUMENTS = DATA_DIR / "instruments.parquet"


def _upsert(path: Path, new: pd.DataFrame, keys: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = pd.read_parquet(path)
        merged = pd.concat([old, new], ignore_index=True)
        merged = merged.drop_duplicates(subset=keys, keep="last")
    else:
        merged = new
    merged.sort_values(keys).to_parquet(path, index=False)


def upsert_bars(df: pd.DataFrame) -> None:
    _upsert(BARS, df, ["stock_id", "date"])


def upsert_dividends(df: pd.DataFrame) -> None:
    _upsert(DIVIDENDS, df, ["stock_id", "date"])


def save_instruments(df: pd.DataFrame) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(INSTRUMENTS, index=False)


def load_bars(stock_id: str, final_only: bool = False) -> pd.DataFrame:
    """讀單一標的的日線，index=date。final_only=True 時排除盤中未定版的 K。"""
    if not BARS.exists():
        return pd.DataFrame()
    df = pd.read_parquet(BARS, filters=[("stock_id", "==", stock_id)])
    if final_only and "is_final" in df.columns:
        df = df[df["is_final"]]
    return df.set_index(pd.to_datetime(df["date"])).sort_index()


def load_dividends(stock_id: str) -> pd.DataFrame:
    if not DIVIDENDS.exists():
        return pd.DataFrame(columns=["date", "cash_dividend", "stock_dividend"])
    df = pd.read_parquet(DIVIDENDS)
    return df[df["stock_id"] == stock_id]


def load_all_dividends() -> pd.DataFrame:
    """讀全市場除權息（供掃描/回測一次還原用）。"""
    if not DIVIDENDS.exists():
        return pd.DataFrame(columns=["stock_id", "date", "cash_dividend", "stock_dividend"])
    return pd.read_parquet(DIVIDENDS)


def load_instruments() -> pd.DataFrame:
    if not INSTRUMENTS.exists():
        return pd.DataFrame(columns=["stock_id", "name", "market"])
    return pd.read_parquet(INSTRUMENTS)


def load_all_bars(final_only: bool = False) -> pd.DataFrame:
    """讀取全市場所有 K 棒（長表），供訊號掃描用。"""
    if not BARS.exists():
        return pd.DataFrame()
    df = pd.read_parquet(BARS)
    if final_only and "is_final" in df.columns:
        df = df[df["is_final"]]
    return df


def resolve(query: str) -> str | None:
    """需求 2-2：用股票代號或名稱查詢，回傳 stock_id。"""
    inst = load_instruments()
    if inst.empty:
        return query.strip() or None
    q = query.strip()
    hit = inst[inst["stock_id"] == q]
    if not hit.empty:
        return q
    hit = inst[inst["name"].astype(str).str.contains(q, na=False)]
    return hit.iloc[0]["stock_id"] if not hit.empty else None