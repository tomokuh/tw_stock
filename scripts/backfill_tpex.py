"""補齊上櫃股(TPEx)的五年歷史。

背景：原始回補漏掉了上櫃股，導致 902/903 檔上櫃股資料嚴重不足
（中位數僅 22 筆，應約 1200 筆）。此腳本用 FinMind 重抓所有
「資料筆數不足」的股票的完整五年，補進資料庫。

可續跑：FinMind 額度用盡(402)會存檔並回報進度，過一小時再跑
會自動跳過已補齊的。用法：
  python scripts/backfill_tpex.py
"""
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from twstock_app.core.config import DATA_DIR
from twstock_app.core import store
from twstock_app.ingest.finmind import fetch_prices, RateLimited

BARS = DATA_DIR / "bars.parquet"
MIN_ROWS = 500          # 資料筆數低於此視為「需補齊」
TOKEN = os.environ.get("FINMIND_TOKEN", "")


def main():
    if not TOKEN:
        print("需要 FINMIND_TOKEN 環境變數")
        sys.exit(1)

    df = pd.read_parquet(BARS)
    df["date"] = pd.to_datetime(df["date"])

    # 找出資料不足的股票
    counts = df.groupby("stock_id").size()
    need = sorted(counts[counts < MIN_ROWS].index.tolist())
    print(f"需補齊的股票（資料<{MIN_ROWS}筆）：{len(need)} 檔")

    end = date.today()
    start = end - timedelta(days=365 * 5 + 30)
    start_s, end_s = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    done = 0
    for i, sid in enumerate(need, 1):
        try:
            new = fetch_prices(sid, start_s, end_s, TOKEN)
            if new.empty:
                print(f"  [{i}/{len(need)}] {sid}: FinMind 無資料")
                continue
            store.upsert_bars(new)
            done += 1
            print(f"  [{i}/{len(need)}] {sid}: 補 {len(new)} 筆")
            time.sleep(0.3)
        except RateLimited:
            print(f"\nFinMind 額度用盡。已補 {done} 檔，進度到第 {i}。")
            print("過一小時再跑一次，會自動跳過已補齊的。")
            break
        except Exception as e:
            print(f"  [{i}/{len(need)}] {sid}: 失敗 {e}")

    print(f"\n本輪補齊 {done} 檔。")
    # 顯示還剩多少
    df2 = pd.read_parquet(BARS)
    c2 = df2.groupby("stock_id").size()
    print(f"仍不足的股票：{(c2 < MIN_ROWS).sum()} 檔（跑到 0 就全補齊）")


if __name__ == "__main__":
    main()