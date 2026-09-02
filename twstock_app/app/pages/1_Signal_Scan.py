from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pandas as pd
import streamlit as st

from twstock_app.core import store
from twstock_app.core.config import Settings
from twstock_app.core.favorites import load_favorites
from twstock_app.core.fav_signals import check_favorites
from twstock_app.core.scan import scan_signals

st.set_page_config(page_title="訊號掃描", layout="wide")
st.title("四色訊號掃描")

S = Settings.load()


@st.cache_data(ttl=1800)
def run_scan(as_of_str: str | None):
    bars = store.load_all_bars()
    inst = store.load_instruments()
    if bars.empty:
        return None
    as_of = pd.Timestamp(as_of_str) if as_of_str else None
    return scan_signals(bars, inst, S, as_of)


bars = store.load_all_bars()
if bars.empty:
    st.warning("尚無資料，請先執行 backfill.py")
    st.stop()

all_dates = sorted(pd.to_datetime(bars["date"]).dt.date.unique())
c1, c2 = st.columns([1, 3])
with c1:
    pick = st.selectbox("掃描日期", all_dates[::-1], index=0,
                        format_func=lambda d: d.isoformat())

# ========== 我的收藏訊號（頁面最上方） ==========
favs = load_favorites()
if favs:
    inst = store.load_instruments()
    fav_res = check_favorites(bars, inst, favs, S, pd.Timestamp(pick))
    n_buy, n_sell = len(fav_res["buy"]), len(fav_res["sell"])

    st.subheader("⭐ 我的收藏訊號")
    if n_buy or n_sell:
        if n_buy:
            st.success(f"🔴 買入訊號 {n_buy} 檔（黑之後第一個紅，可進場）")
            st.dataframe(fav_res["buy"], use_container_width=True, hide_index=True)
        if n_sell:
            st.error(f"⚫ 賣出訊號 {n_sell} 檔（紅之後第一個黑，可出場）")
            st.dataframe(fav_res["sell"], use_container_width=True, hide_index=True)
    else:
        st.info(f"收藏股票在 {pick} 無新的進出場訊號")

    with st.expander(f"收藏股票目前部位狀態（共 {len(favs)} 檔）"):
        st.caption("依最近一次進出場訊號判斷目前該持有還是空手")
        st.dataframe(fav_res["status"], use_container_width=True, hide_index=True)
    st.divider()

# ========== 全市場掃描 ==========
res = run_scan(pd.Timestamp(pick).isoformat())

fc = S.four_color
red_desc = (f"創 {fc.red_price_lookback} 日收盤新高 且 量 > 前 {fc.red_vol_lookback} 日均量 × {fc.red_vol_ratio:g}")
black_desc = (f"創 {fc.black_price_lookback} 日收盤新低 且 量 > 前 {fc.black_vol_lookback} 日均量 × {fc.black_vol_ratio:g}")
st.caption(f"選股池門檻：收盤 ≥ {S.universe.min_close} 元、"
           f"滾動 {S.universe.volume_window} 日中位量 ≥ {S.universe.min_volume_lots} 張")

col_buy, col_sell = st.columns(2)
with col_buy:
    st.subheader(f"🔴 買進訊號　{len(res['buy'])} 檔")
    st.caption(f"當日剛轉入紅色（{red_desc}）")
    st.dataframe(res["buy"], use_container_width=True, hide_index=True, height=560)
with col_sell:
    st.subheader(f"⚫ 賣出訊號　{len(res['sell'])} 檔")
    st.caption(f"當日剛轉入黑色（{black_desc}）")
    st.dataframe(res["sell"], use_container_width=True, hide_index=True, height=560)

if len(res["buy"]) or len(res["sell"]):
    both = pd.concat([
        res["buy"].assign(訊號="買進"),
        res["sell"].assign(訊號="賣出"),
    ], ignore_index=True)
    st.download_button(
        "下載掃描結果 CSV",
        both.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"signals_{pick.isoformat()}.csv",
        mime="text/csv",
    )