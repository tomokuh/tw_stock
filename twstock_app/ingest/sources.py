"""資料擷取層：官方 API。

當日收盤 -> fetch_close_all()  : www.twse.com.tw / www.tpex.org.tw 當日端點
                                （openapi.twse.com.tw 是隔日更新，不用於當日抓取）
盤中快照 -> fetch_intraday()   : MIS 即時報價（含買進/賣出價）
除權息   -> fetch_dividends()  : 供還原權值用

要點：
- 日期一律取自資料本身，並會從指定日往回找「最近一個有資料的交易日」，
  避免遇到週末/假日/當日尚未更新時抓到空表。
- 過濾權證/ETN/TDR，只留個股(4碼數字)與 ETF(00開頭)。
"""
from __future__ import annotations

import re
import time
import warnings
from datetime import date, timedelta

import pandas as pd
import requests
import urllib3

TWSE_MI_INDEX = "https://www.twse.com.tw/exchangeReport/MI_INDEX"
TPEX_DAILY = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
TWSE_DIVIDEND = "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL"
MIS_QUOTE = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"

HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 25

_session = requests.Session()
_session.headers.update(HEADERS)

# 只留個股與 ETF，濾掉權證/ETN/TDR
_EQUITY_RE = re.compile(r"\d{4}")
_ETF_RE = re.compile(r"00\d{2,4}")


def _keep(sid: str) -> bool:
    sid = str(sid).strip()
    return bool(_EQUITY_RE.fullmatch(sid) or _ETF_RE.fullmatch(sid))


def _num(x) -> float:
    try:
        return float(str(x).replace(",", "").strip())
    except (ValueError, AttributeError):
        return float("nan")


def _get(url, *, params=None):
    r = _session.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r


def _get_lenient(url, *, params=None):
    try:
        return _get(url, params=params)
    except requests.exceptions.SSLError:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            r = _session.get(url, params=params, timeout=TIMEOUT, verify=False)
            r.raise_for_status()
            return r


def _recent_weekdays(from_date: date, n: int = 8) -> list[str]:
    """從 from_date 往回取 n 個工作日（跳過六日），回傳 YYYYMMDD 字串。"""
    out = []
    d = from_date
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return out


def _fetch_twse_one(ymd: str) -> pd.DataFrame | None:
    """抓某一天的上市個股。無資料回 None。"""
    r = _get_lenient(TWSE_MI_INDEX,
                     params={"response": "json", "date": ymd, "type": "ALLBUT0999"})
    j = r.json()
    if j.get("stat") != "OK" or not j.get("tables"):
        return None
    tbl = next((t for t in j["tables"]
                if t.get("fields") and "證券代號" in t["fields"] and "收盤價" in t["fields"]),
               None)
    if not tbl or not tbl.get("data"):
        return None
    f = tbl["fields"]
    ci = {name: f.index(name) for name in f}
    src_date = pd.to_datetime(j.get("date", ymd), format="%Y%m%d", errors="coerce")
    if pd.isna(src_date):
        src_date = pd.to_datetime(ymd, format="%Y%m%d")
    rows = []
    for x in tbl["data"]:
        sid = x[ci["證券代號"]].strip()
        if not _keep(sid):
            continue
        rows.append({
            "stock_id": sid,
            "name": x[ci["證券名稱"]].strip(),
            "open": _num(x[ci["開盤價"]]),
            "high": _num(x[ci["最高價"]]),
            "low": _num(x[ci["最低價"]]),
            "close": _num(x[ci["收盤價"]]),
            "volume": _num(x[ci["成交股數"]]) / 1000,
            "market": "TWSE",
        })
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["date"] = src_date
    return df


def _fetch_tpex_one(ymd: str) -> pd.DataFrame | None:
    """抓某一天的上櫃個股。端點結構若有變動則回 None（不中斷上市）。"""
    try:
        r = _get_lenient(TPEX_DAILY, params={"response": "json", "date": ymd})
        j = r.json()
    except Exception:
        return None
    aa = j.get("aaData") or (j.get("tables", [{}])[0].get("data", []) if j.get("tables") else [])
    rows = []
    for x in aa:
        try:
            sid = str(x[0]).strip()
            if not _keep(sid):
                continue
            rows.append({
                "stock_id": sid,
                "name": str(x[1]).strip(),
                "close": _num(x[2]),
                "open": _num(x[4]),
                "high": _num(x[5]),
                "low": _num(x[6]),
                "volume": _num(x[7]) / 1000,
                "market": "TPEx",
            })
        except (IndexError, TypeError):
            continue
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(ymd, format="%Y%m%d")
    return df


def fetch_close_all(trade_date: date | None = None) -> pd.DataFrame:
    """當日全市場日 OHLCV。會從指定日往回找最近一個有資料的交易日。"""
    start = trade_date or date.today()
    tw = None
    used_ymd = None
    # 上市：往回找最近有資料的交易日
    for ymd in _recent_weekdays(start):
        tw = _fetch_twse_one(ymd)
        if tw is not None:
            used_ymd = ymd
            break
    frames = []
    if tw is not None:
        frames.append(tw)
    else:
        print("[warn] 上市當日資料抓不到（近 8 個交易日皆空）")

    # 上櫃：用跟上市相同的交易日（對齊）
    if used_ymd:
        tp = _fetch_tpex_one(used_ymd)
        if tp is not None:
            frames.append(tp)
        else:
            print("[warn] 上櫃當日資料略過（端點結構可能變動，不影響上市）")

    if not frames:
        return pd.DataFrame(columns=["stock_id", "name", "open", "high", "low",
                                     "close", "volume", "market", "date", "is_final"])
    df = pd.concat(frames, ignore_index=True)
    df["is_final"] = True
    return df.dropna(subset=["close"]).query("close > 0").reset_index(drop=True)


def fetch_intraday(stock_ids: list[str], markets: dict[str, str]) -> pd.DataFrame:
    rows, batch = [], 90
    for i in range(0, len(stock_ids), batch):
        chunk = stock_ids[i:i + batch]
        ex_ch = "|".join(
            f"{'otc' if markets.get(s) == 'TPEx' else 'tse'}_{s}.tw" for s in chunk
        )
        r = _get_lenient(MIS_QUOTE, params={"ex_ch": ex_ch, "json": 1, "delay": 0})
        for m in r.json().get("msgArray", []):
            rows.append({
                "stock_id": m.get("c"), "name": m.get("n"),
                "open": _num(m.get("o")), "high": _num(m.get("h")),
                "low": _num(m.get("l")), "close": _num(m.get("z")),
                "bid": _num((m.get("b") or "").split("_")[0]),
                "ask": _num((m.get("a") or "").split("_")[0]),
                "volume": _num(m.get("v")),
            })
        time.sleep(2)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.Timestamp(date.today())
    df["is_final"] = False
    return df


def fetch_dividends() -> pd.DataFrame:
    empty = pd.DataFrame(columns=["stock_id", "date", "cash_dividend", "stock_dividend"])
    try:
        r = _get(TWSE_DIVIDEND)
        payload = r.json()
    except (requests.exceptions.RequestException, ValueError) as e:
        print(f"[warn] 除權息端點無法解析，略過（不影響 K 線入庫）: {e}")
        return empty
    df = pd.DataFrame(payload)
    if df.empty or "Code" not in df.columns:
        return empty
    return pd.DataFrame({
        "stock_id": df["Code"].astype(str),
        "date": pd.to_datetime(df.get("Date"), format="%Y%m%d", errors="coerce"),
        "cash_dividend": df.get("CashDividend", 0).map(_num).fillna(0)
                         if "CashDividend" in df.columns else 0,
        "stock_dividend": (df.get("StockDividend", 0).map(_num).fillna(0) / 1000)
                          if "StockDividend" in df.columns else 0,
    }).dropna(subset=["date"])