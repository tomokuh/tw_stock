"""每日盤後定版 + 自動補洞。排程 19:00 呼叫，或手動執行。

抓「缺的交易日」-> upsert 進 bars。
  自動補洞：從資料庫最新日期之後到今天，逐一補上所有缺的交易日。
            已有的跳過，只抓缺的。漏抓好幾天（電腦沒開）時，
            下次跑一次就自動補齊，不必手動指定日期。
  過濾：只寫入 close > 0 的資料，擋掉冷門股無量日回傳的 0 值。
instruments 用「合併」而非覆蓋：當日抓到的補進去，原有的保留，
  避免某天上市或上櫃抓取不完整時，把完整的股票清單洗掉。
"""
import sys
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from twstock_app.core import store
from twstock_app.core.config import DATA_DIR
from twstock_app.ingest.sources import fetch_close_all, fetch_dividends


def _existing_dates() -> set:
    df = store.load_all_bars()
    if df.empty:
        return set()
    return set(pd.to_datetime(df["date"]).dt.date)


def _target_days(have: set, today: date, scan_back: int = 30) -> list[date]:
    """要嘗試抓的日子：近 scan_back 天內「所有缺的工作日」（含中間的洞）。
    不只補最新之後——掃描整個近期範圍找缺口。
    資料庫空則只抓今天（歷史用 backfill.py）。"""
    if not have:
        return [today]
    out = []
    d = today - timedelta(days=scan_back)
    while d <= today:
        if d.weekday() < 5 and d not in have:
            out.append(d)
        d += timedelta(days=1)
    return out or [today]   # 沒缺口也抓一次今天（盤後可能剛更新）


have = _existing_dates()
today = date.today()
targets = _target_days(have, today)
print(f"準備補 {len(targets)} 個交易日")

written = 0
inst_frames = []
for d in targets:
    bars = fetch_close_all(d)
    bars = bars[bars["close"] > 0] if not bars.empty else bars   # 過濾 0 值
    if bars.empty:
        print(f"  {d}: 無資料（非交易日或尚未更新），略過")
        continue
    got = pd.to_datetime(bars["date"]).dt.date.iloc[0]
    if got in have:
        continue   # 往回找又回到已有的日，跳過
    store.upsert_bars(bars)
    inst_frames.append(bars[["stock_id", "name", "market"]])
    have.add(got)
    written += 1
    tag = f"（實際交易日 {got}）" if got != d else ""
    print(f"  {d}: {len(bars)} 檔已定版{tag}")

# instruments 合併：新舊聯集，不覆蓋
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