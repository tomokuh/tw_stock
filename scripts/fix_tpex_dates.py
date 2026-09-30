"""
修復被 TPEx 端點污染的上櫃歷史資料。
支援 progress.json 斷點續抓，避免重複消耗 FinMind API 額度。

用法：
  python scripts/fix_tpex_dates.py
"""

import os
import sys
import time
import json
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from twstock_app.core.config import DATA_DIR
from twstock_app.core import store
from twstock_app.ingest.finmind import fetch_prices, RateLimited


BARS = DATA_DIR / "bars.parquet"
PROGRESS = DATA_DIR / "progress.json"

TOKEN = os.environ.get("FINMIND_TOKEN", "")


def load_progress():
    """讀取已完成的股票清單"""
    if not PROGRESS.exists():
        return {}

    try:
        with open(PROGRESS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"讀取 progress.json 失敗：{e}")
        return {}


def save_progress(progress):
    """儲存進度"""
    temp_file = PROGRESS.with_suffix(".tmp")

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=4)

    # 避免寫入途中程式中斷造成 progress.json 損壞
    temp_file.replace(PROGRESS)


def main():
    if not TOKEN:
        print("需要 FINMIND_TOKEN 環境變數")
        sys.exit(1)

    # -----------------------------
    # 讀取股票清單
    # -----------------------------
    inst = pd.read_parquet(DATA_DIR / "instruments.parquet")

    tpex_ids = sorted(
        inst[inst["market"] == "TPEx"]["stock_id"]
        .astype(str)
        .tolist()
    )

    # -----------------------------
    # 讀取進度
    # -----------------------------
    progress = load_progress()

    completed = {
        sid for sid, done in progress.items()
        if done is True
    }

    remaining = [
        sid for sid in tpex_ids
        if sid not in completed
    ]

    print(f"上櫃股共 {len(tpex_ids)} 檔")
    print(f"已完成：{len(completed)} 檔")
    print(f"剩餘：{len(remaining)} 檔")

    if not remaining:
        print("所有上櫃股票都已完成，不需要重新抓取。")
        return

    print("使用 FinMind 重抓五年資料，開始處理…")

    # -----------------------------
    # 日期範圍
    # -----------------------------
    end = date.today()
    start = end - timedelta(days=365 * 5 + 30)

    start_s = start.strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")

    print(f"資料範圍：{start_s} ~ {end_s}")

    # -----------------------------
    # 讀取目前 bars
    # -----------------------------
    df_all = pd.read_parquet(BARS)
    df_all["date"] = pd.to_datetime(df_all["date"])

    done = len(completed)

    # -----------------------------
    # 開始逐檔處理
    # -----------------------------
    for i, sid in enumerate(remaining, 1):

        try:
            print(
                f"  [{i}/{len(remaining)}] "
                f"{sid}: 開始抓取…"
            )

            new = fetch_prices(
                sid,
                start_s,
                end_s,
                TOKEN
            )

            if new.empty:
                print(
                    f"  [{i}/{len(remaining)}] "
                    f"{sid}: FinMind 無資料"
                )

                # 無資料不標記為完成
                # 下次執行仍會重新嘗試
                continue

            new["market"] = "TPEx"

            # -----------------------------
            # 刪除舊資料
            # -----------------------------
            df_all = df_all[
                df_all["stock_id"] != sid
            ]

            # -----------------------------
            # 加入 FinMind 正確資料
            # -----------------------------
            df_all = pd.concat(
                [df_all, new],
                ignore_index=True
            )

            done += 1

            # -----------------------------
            # 記錄 progress
            # -----------------------------
            progress[sid] = True
            save_progress(progress)

            print(
                f"  [{i}/{len(remaining)}] "
                f"{sid}: 重抓 {len(new)} 筆 ✓"
            )

            # -----------------------------
            # 每 20 檔存一次 bars
            # -----------------------------
            if done % 20 == 0:
                df_all.to_parquet(
                    BARS,
                    index=False
                )

                print(
                    f"    （已存檔，累計完成 {done} 檔）"
                )

            time.sleep(0.3)

        except RateLimited:

            # API 額度用完之前先保存目前資料
            df_all.to_parquet(
                BARS,
                index=False
            )

            # progress.json 已經在每檔成功後立即保存
            # 所以下次執行不會重新抓已完成的股票

            print(
                "\nFinMind 額度用盡。"
            )

            print(
                f"已完成 {done} 檔。"
            )

            print(
                "目前進度已保存到："
            )

            print(
                f"  {PROGRESS}"
            )

            print(
                "額度恢復後再次執行即可從未完成的股票繼續。"
            )

            return

        except Exception as e:

            print(
                f"  [{i}/{len(remaining)}] "
                f"{sid}: 失敗 {e}"
            )

            # 失敗不寫入 progress
            # 下次執行會重新嘗試

    # -----------------------------
    # 最後完整保存
    # -----------------------------
    df_all.to_parquet(
        BARS,
        index=False
    )

    print(
        f"\n完成：本次重抓 {done - len(completed)} 檔。"
    )

    print(
        f"總計完成：{len(progress)} 檔上櫃股。"
    )

    print(
        "已覆蓋污染資料。"
    )


if __name__ == "__main__":
    main()

