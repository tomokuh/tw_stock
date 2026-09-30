
from __future__ import annotations

import time
import warnings
from datetime import date

import pandas as pd
import requests
import urllib3

TPEX_STOCK = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
HEADERS = {"User-Agent": "Mozilla/5.0 (NCKU-CS-student-project)"}
TIMEOUT = 25

_session = requests.Session()
_session.headers.update(HEADERS)


def _num(x) -> float:
    try:
        return float(str(x).replace(",", "").strip())
    except (ValueError, AttributeError):
        return float("nan")


def _roc_to_ts(s: str):
    """民國 115/08/03 -> Timestamp(2026-08-03)。"""
    p = s.strip().split("/")
    return pd.Timestamp(f"{int(p[0]) + 1911}-{p[1]}-{p[2]}")


def fetch_month(stkno: str, year: int, month: int) -> pd.DataFrame:
    """抓單一上櫃股某年某月的日 OHLCV。回傳長表（欄位對齊系統）。"""
    ds = f"{year}/{month:02d}/01"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            r = _session.get(TPEX_STOCK,
                             params={"code": stkno, "date": ds, "response": "json"},
                             timeout=TIMEOUT, verify=False)
        r.raise_for_status()
        j = r.json()
    except Exception:
        return pd.DataFrame(columns=["stock_id", "date", "open", "high", "low", "close", "volume"])

    tables = j.get("tables") or []
    if not tables or not tables[0].get("data"):
        return pd.DataFrame(columns=["stock_id", "date", "open", "high", "low", "close", "volume"])

    rows = []
    for x in tables[0]["data"]:
        try:
            # x[0]日期 x[1]成交張數 x[2]成交仟元 x[3]開 x[4]高 x[5]低 x[6]收 x[7]漲跌 x[8]筆數
            rows.append({
                "stock_id": str(stkno),
                "date": _roc_to_ts(x[0]),
                "open": _num(x[3]),
                "high": _num(x[4]),
                "low": _num(x[5]),
                "close": _num(x[6]),
                "volume": _num(x[1]),   # 已是「張」，不用除 1000
            })
        except (IndexError, TypeError, ValueError):
            continue
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.dropna(subset=["close"]).query("close > 0").reset_index(drop=True)


def fetch_history(stkno: str, start: date, end: date, sleep: float = 0.2) -> pd.DataFrame:
    """抓單一上櫃股 start~end 期間的完整日 OHLCV（自動逐月抓）。"""
    frames = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        df = fetch_month(stkno, y, m)
        if not df.empty:
            frames.append(df)
        time.sleep(sleep)   # 官方無額度限制，但禮貌性延遲
        m += 1
        if m > 12:
            m = 1; y += 1
    if not frames:
        return pd.DataFrame(columns=["stock_id", "date", "open", "high", "low", "close", "volume"])
    out = pd.concat(frames, ignore_index=True)
    out = out[(out["date"] >= pd.Timestamp(start)) & (out["date"] <= pd.Timestamp(end))]
    return out.drop_duplicates(subset=["stock_id", "date"]).reset_index(drop=True)