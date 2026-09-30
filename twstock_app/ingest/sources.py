"""資料擷取層：官方 API。
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

HEADERS = {"User-Agent": "Mozilla/5.0 (NCKU-CS-student-project)"}
TIMEOUT = 25

_session = requests.Session()
_session.headers.update(HEADERS)

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
    out = []
    d = from_date
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return out


def _fetch_twse_one(ymd: str) -> pd.DataFrame | None:
    """抓某一天的上市個股。TWSE 端點吃 date=YYYYMMDD，可查歷史。無資料回 None。"""
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
    """抓某一天的上櫃個股。吃歷史，一次全市場。

    ★ 關鍵：dailyQuotes 的 date 參數要用「YYYY/MM/DD」帶斜線格式（西元）。
      傳入的 ymd 是 YYYYMMDD，這裡轉成 YYYY/MM/DD 再送。
      仍核對端點回報日期，不符回 None（防萬一污染）。

    TPEx 欄位：x[2]收盤 x[4]開 x[5]高 x[6]低 x[7]均價 x[8]成交股數
    成交量用 x[8]（成交股數），x[7] 是均價。
    """
    # YYYYMMDD -> YYYY/MM/DD（dailyQuotes 需要帶斜線才吃歷史）
    date_slash = f"{ymd[0:4]}/{ymd[4:6]}/{ymd[6:8]}"
    try:
        r = _get_lenient(TPEX_DAILY, params={"response": "json",
                                             "date": date_slash, "type": "AL"})
        j = r.json()
    except Exception:
        return None

    # 端點回報的實際日期（YYYYMMDD）；不等於要求日就拒絕（避免污染）
    ep_date = str(j.get("date", "")).strip()
    if ep_date and ep_date != ymd:
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
                "volume": _num(x[8]) / 1000,   # x[8]=成交股數（股）->張
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
    """全市場日 OHLCV。往回找最近一個有資料的交易日。

    上市 TWSE、上櫃 TPEx dailyQuotes 都吃歷史（用對日期格式），
    所以補當日或補過去日都可用，一天各一次請求。
    """
    start = trade_date or date.today()
    tw = None
    used_ymd = None
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

    # 上櫃：用跟上市相同的交易日（dailyQuotes 吃歷史，補過去日也 OK）
    if used_ymd:
        tp = _fetch_tpex_one(used_ymd)
        if tp is not None:
            frames.append(tp)
        else:
            print(f"[warn] 上櫃 {used_ymd} 無資料或日期不符，略過")

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