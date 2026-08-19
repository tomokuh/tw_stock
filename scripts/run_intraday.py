"""11:30 盤中快照（is_final=False，不進四色訊號）。cron:  30 11 * * 1-5"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twstock_app.core import store
from twstock_app.ingest.sources import fetch_intraday

inst = store.load_instruments()
if inst.empty:
    raise SystemExit("請先跑一次 scripts/run_close.py 建立標的清單")

markets = dict(zip(inst.stock_id, inst.market))
snap = fetch_intraday(inst.stock_id.tolist(), markets)
store.upsert_bars(snap)
print(f"[intraday] {len(snap)} 檔快照完成")