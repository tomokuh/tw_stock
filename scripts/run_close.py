"""每日盤後定版 + 自動補洞（用筆數判斷完整性）。排程 19:00 呼叫，或手動執行。

抓「缺或殘缺的交易日」-> upsert 進 bars。
  ★ 用「當日筆數」判斷，而非「日期在不在」：
    某交易日總筆數 < MIN_ROWS（如殘缺日）視為未完整，會重新抓補齊。
  自動補洞：掃近 scan_back 天，所有「缺或殘缺」的工作日都補。
  過濾：只寫入 close > 0 的資料。

  上市 TWSE、上櫃 TPEx dailyQuotes 都吃歷史（sources.py 用對日期格式），
  所以補過去日時上市上櫃一次都補齊，不需逐檔補救。
instruments 用「合併」而非覆蓋。
"""
import sys
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from twstock_app.core import store
from twstock_app.core.config import DATA_DIR
from twstock_app.ingest.sources import fetch_close_all, fetch_dividends

# 某交易日總筆數 < 此值視為未完整（缺或殘缺），需重補。正常日約 2000+ 檔。
MIN_ROWS = 1400


def _date_counts() -> dict:
    """{日期: 該日總筆數}。用筆數判斷完整性。"""
    df = store.load_all_bars()
    if df.empty:
        return {}
    return pd.to_datetime(df["date"]).dt.date.value_counts().to_dict()


def _complete_dates(counts: dict) -> set:
    """筆數 >= MIN_ROWS 才算完整。"""
    return {d for d, n in counts.items() if n >= MIN_ROWS}


def _target_days(complete: set, today: date, scan_back: int = 30) -> list[date]:
    """近 scan_back 天內所有「未完整」的工作日（缺的 + 殘缺的）。"""
    if not complete:
        return [today]
    out = []
    d = today - timedelta(days=scan_back)
    while d <= today:
        if d.weekday() < 5 and d not in complete:
            out.append(d)
        d += timedelta(days=1)
    return out or [today]


counts = _date_counts()
complete = _complete_dates(counts)
today = date.today()
targets = _target_days(complete, today)
print(f"準備補 {len(targets)} 個交易日（含殘缺日重補）")

written = 0
inst_frames = []
for d in targets:
    bars = fetch_close_all(d)
    bars = bars[bars["close"] > 0] if not bars.empty else bars
    if bars.empty:
        print(f"  {d}: 無資料（非交易日或尚未更新），略過")
        continue
    got = pd.to_datetime(bars["date"]).dt.date.iloc[0]
    if got in complete:
        continue   # 往回找又回到已完整的日，跳過
    store.upsert_bars(bars)
    inst_frames.append(bars[["stock_id", "name", "market"]])
    written += 1
    n_before = counts.get(got, 0)
    fix_tag = f"（原殘缺 {n_before} 筆，已重補）" if 0 < n_before < MIN_ROWS else ""
    tag = f"（實際交易日 {got}）" if got != d else ""
    print(f"  {d}: {len(bars)} 檔已定版{tag}{fix_tag}")

# instruments 合併
if inst_frames:
    inst_path = DATA_DIR / "instruments.parquet"
    new_inst = pd.concat(inst_frames, ignore_index=True).drop_duplicates("stock_id")
    if inst_path.exists():
        old_inst = pd.read_parquet(inst_path)
        merged = (pd.concat([old_inst, new_inst], ignore_index=True)
                  .drop_duplicates("stock_id", keep="last"))
    else:
        merged = new_inst
    merged.to_parquet(inst_path, index=False)

try:
    store.upsert_dividends(fetch_dividends())
except Exception as e:
    print(f"  除權息略過: {e}")

print(f"[close] 共補 {written} 個交易日")