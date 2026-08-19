"""五年歷史回補（一次性）。可中斷後續跑——已抓過的檔會自動跳過。
    python scripts/backfill.py              # 回補五年
    python scripts/backfill.py --years 3    # 只回補三年
"""
import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from twstock_app.core import store
from twstock_app.core.config import UniverseConfig
from twstock_app.ingest import finmind


def already_have(stock_id: str, need_start: pd.Timestamp) -> bool:
    """該檔是否已回補到夠早的日期——是則跳過，達成可續跑。"""
    df = store.load_bars(stock_id)
    if df.empty:
        return False
    return df.index.min() <= need_start + pd.Timedelta(days=7)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--sleep", type=float, default=6.5, help="每次 request 間隔秒數（避開限流）")
    args = ap.parse_args()

    end = date.today()
    start = end - timedelta(days=365 * args.years + 10)
    start_s, end_s = start.isoformat(), end.isoformat()
    need_start = pd.Timestamp(start)

    print(f"回補範圍 {start_s} ~ {end_s}")
    print("取得股票清單…")
    stocks = finmind.fetch_stock_list()
    market_map = dict(zip(stocks.stock_id, stocks.market))
    store.save_instruments(stocks)
    print(f"共 {len(stocks)} 檔（上市+上櫃）")

    done = skipped = failed = 0
    for i, sid in enumerate(stocks.stock_id, 1):
        if already_have(sid, need_start):
            skipped += 1
            continue
        try:
            df = finmind.fetch_prices(sid, start_s, end_s)
            if not df.empty:
                df["market"] = market_map.get(sid, "")
                store.upsert_bars(df)
                done += 1
            time.sleep(args.sleep)
        except finmind.RateLimited:
            print(f"  [{i}/{len(stocks)}] 達每小時上限，暫停 60 分鐘後自動續跑…")
            time.sleep(3660)
        except Exception as e:
            failed += 1
            print(f"  [{i}/{len(stocks)}] {sid} 失敗: {e}")
            time.sleep(args.sleep)

        if i % 50 == 0:
            print(f"  進度 {i}/{len(stocks)}  新增 {done} 跳過 {skipped} 失敗 {failed}")

    print("回補除權息表…")
    try:
        store.upsert_dividends(finmind.fetch_dividends())
    except Exception as e:
        print(f"  除權息回補略過: {e}")

    print(f"\n完成：新增 {done}、跳過 {skipped}（已有）、失敗 {failed}")
    print("接著執行  streamlit run twstock_app/app/main.py")


if __name__ == "__main__":
    main()