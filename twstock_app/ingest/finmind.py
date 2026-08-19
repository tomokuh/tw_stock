"""FinMind 歷史資料客戶端——供五年回補用。
"""
from __future__ import annotations

import os
import re

import pandas as pd
import requests

API = "https://api.finmindtrade.com/api/v4/data"

# 只保留個股與 ETF，濾掉權證/ETN/TDR：
#   個股 = 純 4 碼數字（2330、2317）
#   ETF  = 00 開頭純數字（0050、00878、00929）
#   濾掉 = 含字母（00400A、2330A、03001P）或非上述長度（910322 TDR）
_EQUITY_RE = re.compile(r"\d{4}")
_ETF_RE = re.compile(r"00\d{2,4}")


def _is_equity_or_etf(sid: str) -> bool:
    sid = str(sid).strip()
    return bool(_EQUITY_RE.fullmatch(sid) or _ETF_RE.fullmatch(sid))


def _headers(token: str | None) -> dict:
    token = token or os.environ.get("FINMIND_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def fetch_stock_list(token: str | None = None) -> pd.DataFrame:
    """全部台股清單（上市 twse + 上櫃 otc），僅個股與 ETF，已濾掉權證/ETN/TDR。"""
    r = requests.get(
        API, params={"dataset": "TaiwanStockInfo"}, headers=_headers(token), timeout=30
    )
    r.raise_for_status()
    df = pd.DataFrame(r.json().get("data", []))
    if df.empty:
        return df
    df = df.drop_duplicates("stock_id")
    df = df[df["type"].isin(["twse", "otc"])]
    # 關鍵過濾：只留個股與 ETF
    df = df[df["stock_id"].astype(str).map(_is_equity_or_etf)]
    return pd.DataFrame({
        "stock_id": df["stock_id"].astype(str),
        "name": df["stock_name"],
        "market": df["type"].map({"twse": "TWSE", "otc": "TPEx"}),
    }).reset_index(drop=True)


def fetch_prices(stock_id: str, start: str, end: str, token: str | None = None) -> pd.DataFrame:
    """單一檔日 OHLCV。start/end 格式 'YYYY-MM-DD'。回傳已正規化的欄位。"""
    r = requests.get(
        API,
        params={
            "dataset": "TaiwanStockPrice",
            "data_id": stock_id,          # 一定要帶，否則會回全市場
            "start_date": start,
            "end_date": end,
        },
        headers=_headers(token),
        timeout=30,
    )
    if r.status_code == 402:
        raise RateLimited(stock_id)
    r.raise_for_status()
    df = pd.DataFrame(r.json().get("data", []))
    if df.empty:
        return pd.DataFrame(columns=["stock_id", "date", "open", "high", "low", "close", "volume"])
    # 保險：確認回傳的確實是這一檔（若 API 異常回了別的，直接丟棄）
    df = df[df["stock_id"].astype(str) == str(stock_id)]
    if df.empty:
        return pd.DataFrame(columns=["stock_id", "date", "open", "high", "low", "close", "volume"])
    return pd.DataFrame({
        "stock_id": df["stock_id"].astype(str),
        "date": pd.to_datetime(df["date"]),
        "open": df["open"].astype(float),
        "high": df["max"].astype(float),
        "low": df["min"].astype(float),
        "close": df["close"].astype(float),
        "volume": df["Trading_Volume"].astype(float) / 1000,  # 股 -> 張
        "market": "",
        "is_final": True,
    })


def fetch_dividends(token: str | None = None) -> pd.DataFrame:
    """除權息結果表（全市場）。before/after 參考價可直接算還原因子。"""
    r = requests.get(
        API, params={"dataset": "TaiwanStockDividendResult"},
        headers=_headers(token), timeout=30,
    )
    r.raise_for_status()
    df = pd.DataFrame(r.json().get("data", []))
    if df.empty:
        return pd.DataFrame(columns=["stock_id", "date", "before_price", "after_price"])
    return pd.DataFrame({
        "stock_id": df["stock_id"].astype(str),
        "date": pd.to_datetime(df["date"]),
        "before_price": df["before_price"].astype(float),
        "after_price": df["after_price"].astype(float),
    })


class RateLimited(Exception):
    """FinMind 回傳 402：達到每小時上限。"""