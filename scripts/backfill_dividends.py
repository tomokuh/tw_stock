"""回補全市場除權息資料 -> dividends.parquet（供 adjust_prices 還原用）。

FinMind TaiwanStockDividend（免費可用）。填好後，K線頁開「還原權值」，
四色就會吃還原價，除權息日不再誤判跳空。

欄位對應：
  CashExDividendTradingDate / StockExDividendTradingDate -> 除息交易日
  CashEarningsDistribution   -> cash_dividend（每股現金股息）
  StockEarningsDistribution  -> stock_dividend（每股配股數，需 /10 轉成比例）

用法：
  python scripts/backfill_dividends.py
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import requests

from twstock_app.core.config import DATA_DIR

API = "https://api.finmindtrade.com/api/v4/data"
TOKEN = os.environ.get("FINMIND_TOKEN", "")
DIV_PATH = DATA_DIR / "dividends.parquet"


def _headers():
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


def fetch_dividend(stock_id, start="2020-01-01", end="2026-12-31"):
    r = requests.get(API, params={
        "dataset": "TaiwanStockDividend", "data_id": stock_id,
        "start_date": start, "end_date": end,
    }, headers=_headers(), timeout=30)
    if r.status_code == 402:
        raise RuntimeError("FinMind 額度用盡(402)")
    r.raise_for_status()
    data = r.json().get("data", [])
    rows = []
    for x in data:
        # 除息交易日：優先現金，其次配股（通常同一天）
        ex = (x.get("CashExDividendTradingDate", "").strip()
              or x.get("StockExDividendTradingDate", "").strip())
        if not ex:
            continue
        cash = float(x.get("CashEarningsDistribution", 0) or 0)
        # StockEarningsDistribution 是「每股配股元」，配股比例 = 元/10（面額10元）
        stock = float(x.get("StockEarningsDistribution", 0) or 0) / 10.0
        if cash == 0 and stock == 0:
            continue
        rows.append({
            "stock_id": str(stock_id),
            "date": pd.to_datetime(ex),
            "cash_dividend": cash,
            "stock_dividend": stock,
        })
    return rows


def main():
    if not TOKEN:
        print("需要 FINMIND_TOKEN 環境變數")
        sys.exit(1)

    inst = pd.read_parquet(DATA_DIR / "instruments.parquet")
    all_ids = sorted(inst["stock_id"].astype(str).tolist())

    # 續跑：已抓過的股票跳過
    have_ids = set()
    if DIV_PATH.exists():
        old = pd.read_parquet(DIV_PATH)
        have_ids = set(old["stock_id"].astype(str))
        all_rows = old.to_dict("records")
    else:
        all_rows = []

    todo = [s for s in all_ids if s not in have_ids]
    print(f"全市場 {len(all_ids)} 檔；已抓 {len(have_ids)} 檔，本輪抓 {len(todo)} 檔除權息…")

    done = 0
    for i, sid in enumerate(todo, 1):
        try:
            rows = fetch_dividend(sid)
            all_rows.extend(rows)   # 沒配息的股票 rows 為空，也算「已抓過」
            have_ids.add(sid)
            done += 1
            if rows:
                print(f"  [{i}/{len(todo)}] {sid}: {len(rows)} 筆除權息")
            time.sleep(0.3)
            if done % 50 == 0:
                pd.DataFrame(all_rows).to_parquet(DIV_PATH, index=False)
                print(f"    （已存檔，累計處理 {len(have_ids)} 檔）")
        except RuntimeError as e:
            pd.DataFrame(all_rows).to_parquet(DIV_PATH, index=False)
            print(f"\n{e}。已存檔，過一小時再跑會自動跳過已抓的。")
            return
        except Exception as e:
            print(f"  [{i}/{len(todo)}] {sid}: 失敗 {e}")

    df = pd.DataFrame(all_rows).drop_duplicates(subset=["stock_id", "date"])
    df.to_parquet(DIV_PATH, index=False)
    print(f"\n完成：除權息共 {len(df)} 筆，涵蓋 {df['stock_id'].nunique()} 檔，已存 {DIV_PATH}")


if __name__ == "__main__":
    main()