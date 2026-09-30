from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from twstock_app.app.chart import build_chart
from twstock_app.core import store
from twstock_app.core.config import COLOR_HEX, Settings
from twstock_app.core.favorites import (add_favorite, load_favorites,
                                        remove_favorite)
from twstock_app.core.four_color import four_color, signals
from twstock_app.core.transform import add_ma, adjust_prices, resample_ohlcv

st.set_page_config(page_title="台股四色 K 線", layout="wide")
S = Settings.load()

RANGE_DAYS = {"3 個月": 63, "6 個月": 126, "1 年": 252, "2 年": 504, "5 年": 1260, "全部": None}

# ---------------- sidebar ----------------
with st.sidebar:
    st.header("查詢")

    favs = load_favorites()
    if favs:
        inst = store.load_instruments()
        name_map = dict(zip(inst["stock_id"].astype(str), inst["name"])) if not inst.empty else {}
        fav_labels = ["（不使用收藏）"] + [f"{s} {name_map.get(s, '')}".strip() for s in favs]
        picked = st.selectbox("★ 我的收藏", fav_labels, index=0)
        if picked != "（不使用收藏）":
            st.session_state["query_from_fav"] = picked.split()[0]

    default_query = st.session_state.get("query_from_fav", "2330")
    query = st.text_input("股票代號或名稱", default_query)
    st.session_state.pop("query_from_fav", None)

    st.header("K 線設定")
    freq_label = st.radio("週期", ["日線", "週線", "月線"], horizontal=True)
    freq = {"日線": "daily", "週線": "weekly", "月線": "monthly"}[freq_label]
    show_adjusted = st.toggle("顯示還原權值價", value=False,
                              help="四色判斷一律用還原價；此開關只切換 K 線「顯示」原始價或還原價。")
    rng_label = st.selectbox("顯示區間", list(RANGE_DAYS), index=2)
    mode = st.selectbox(
        "K 線配色",
        ["four_color", "classic_rg", "classic_rb"],
        format_func=lambda m: {"four_color": "四色 K 線",
                               "classic_rg": "傳統（紅/綠）",
                               "classic_rb": "傳統（紅/藍）"}[m],
    )

    st.header("移動平均線")
    ma_pool = getattr(S.ma, freq)
    price_ma = st.multiselect(
        f"價格均線（最多 {S.ma.price_max_lines} 條）", ma_pool,
        default=ma_pool[:2], max_selections=S.ma.price_max_lines,
    )
    vol_ma = st.multiselect(
        f"成交量均線（{S.ma.volume_min}~{S.ma.volume_max}，最多 {S.ma.volume_max_lines} 條）",
        list(range(S.ma.volume_min, S.ma.volume_max + 1)),
        default=[5, 20], max_selections=S.ma.volume_max_lines,
    )

    plo, phi = S.four_color.ui_lookback_range
    rlo, rhi = S.four_color.ui_vol_ratio_range

    st.header("🔴 紅（買進）條件")
    red_price_lb = st.slider("紅：突破前 N 日最高收盤", plo, phi,
                             S.four_color.red_price_lookback, key="red_price")
    red_vol_lb = st.slider("紅：量 > 前 N 日平均量", plo, phi,
                           S.four_color.red_vol_lookback, key="red_vollb")
    red_vol_ratio = st.slider("紅：量能倍數", rlo, rhi,
                              S.four_color.red_vol_ratio, step=0.01, key="red_ratio")

    st.header("⚫ 黑（賣出）條件")
    black_price_lb = st.slider("黑：跌破前 N 日最低收盤", plo, phi,
                               S.four_color.black_price_lookback, key="black_price")
    black_vol_lb = st.slider("黑：量 > 前 N 日平均量", plo, phi,
                             S.four_color.black_vol_lookback, key="black_vollb")
    black_vol_ratio = st.slider("黑：量能倍數", rlo, rhi,
                                S.four_color.black_vol_ratio, step=0.01, key="black_ratio")

    if st.button("儲存為預設值"):
        S.four_color.red_price_lookback = red_price_lb
        S.four_color.red_vol_lookback = red_vol_lb
        S.four_color.red_vol_ratio = red_vol_ratio
        S.four_color.black_price_lookback = black_price_lb
        S.four_color.black_vol_lookback = black_vol_lb
        S.four_color.black_vol_ratio = black_vol_ratio
        S.save()
        st.success("已寫入 config/settings.yaml")

cfg = S.four_color.model_copy(update={
    "red_price_lookback": red_price_lb, "red_vol_lookback": red_vol_lb,
    "red_vol_ratio": red_vol_ratio,
    "black_price_lookback": black_price_lb, "black_vol_lookback": black_vol_lb,
    "black_vol_ratio": black_vol_ratio,
})

# ---------------- data ----------------
stock_id = store.resolve(query)
if not stock_id:
    st.error(f"查無「{query}」")
    st.stop()

raw = store.load_bars(stock_id, final_only=True)
if raw.empty:
    st.warning("尚無資料。請先執行  python scripts/run_close.py")
    st.stop()

daily = adjust_prices(raw, store.load_dividends(stock_id))

# ★ 四色一律用還原價；K 線顯示依 show_adjusted 切換原始/還原
bars_for_color = resample_ohlcv(daily, freq, adjusted=True)     # 還原價 → 四色判斷
colors = four_color(bars_for_color, cfg)
sig = signals(colors)

bars = resample_ohlcv(daily, freq, adjusted=show_adjusted)      # 顯示用（原始或還原）
bars = add_ma(bars, price_ma, vol_ma)

n = RANGE_DAYS[rng_label]
if n:
    per_bar = {"daily": 1, "weekly": 5, "monthly": 21}[freq]
    view = bars.tail(max(n // per_bar, 10))
    colors_v, sig_v = colors.reindex(view.index), sig.reindex(view.index)
else:
    view, colors_v, sig_v = bars, colors, sig

# ---------------- render ----------------
name = store.load_instruments().query("stock_id == @stock_id")["name"]
name_str = name.iloc[0] if not name.empty else ""
title = f"{stock_id} {name_str} — {freq_label}{'（顯示還原價）' if show_adjusted else ''}"

fav_list = load_favorites()
col_title, col_fav = st.columns([5, 1])
with col_title:
    st.subheader(title)
with col_fav:
    if stock_id in fav_list:
        if st.button("★ 已收藏", help="點擊移除收藏"):
            remove_favorite(stock_id)
            st.rerun()
    else:
        if st.button("☆ 收藏", help="加入收藏"):
            add_favorite(stock_id)
            st.rerun()

st.plotly_chart(
    build_chart(view, colors_v, price_ma, vol_ma, freq, mode, title),
    use_container_width=True,
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("目前顏色", {"red": "紅（買進）", "yellow": "黃（中性偏多）",
                       "blue": "藍（中性偏空）", "black": "黑（賣出）",
                       "gray": "—"}[colors_v.iloc[-1]])
c2.metric("最新收盤", f"{view.close.iloc[-1]:.2f}")
c3.metric("區間買進訊號", int(sig_v.buy.sum()))
c4.metric("區間賣出訊號", int(sig_v.sell.sum()))

with st.expander("資料表"):
    show = view.copy()
    show["顏色"] = colors_v
    st.dataframe(show.tail(60).iloc[::-1], use_container_width=True)