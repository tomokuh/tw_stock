"""個股回測頁：單一標的四色策略（全押）vs 買進持有。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from twstock_app.core import store
from twstock_app.core.config import Settings
from twstock_app.core.single_backtest import SingleBTConfig, run_single, summarize_single

st.set_page_config(page_title="個股回測", layout="wide")
st.title("個股回測：四色策略 vs 買進持有")

S = Settings.load()

with st.sidebar:
    st.header("標的")
    query = st.text_input("股票代號或名稱", "2330")

    st.header("回測參數")
    init_cash = st.number_input("初始資金", 100_000, 100_000_000, 1_000_000, step=100_000)
    st.caption("訊號來時全押、轉黑全出，與買進持有曝險一致")

    plo, phi = S.four_color.ui_lookback_range
    rlo, rhi = S.four_color.ui_vol_ratio_range

    st.header("🔴 紅（買進）條件")
    red_price_lb = st.slider("紅：突破前 N 日最高收盤", plo, phi, S.four_color.red_price_lookback, key="r_p")
    red_vol_lb = st.slider("紅：量 > 前 N 日平均量", plo, phi, S.four_color.red_vol_lookback, key="r_v")
    red_vol_ratio = st.slider("紅：量能倍數", rlo, rhi, S.four_color.red_vol_ratio, 0.01, key="r_r")

    st.header("⚫ 黑（賣出）條件")
    black_price_lb = st.slider("黑：跌破前 N 日最低收盤", plo, phi, S.four_color.black_price_lookback, key="b_p")
    black_vol_lb = st.slider("黑：量 > 前 N 日平均量", plo, phi, S.four_color.black_vol_lookback, key="b_v")
    black_vol_ratio = st.slider("黑：量能倍數", rlo, rhi, S.four_color.black_vol_ratio, 0.01, key="b_r")

    st.header("成本")
    fee = st.number_input("手續費率 %", 0.0, 0.5, 0.1425, 0.01, format="%.4f") / 100
    tax = st.number_input("證交稅率 %", 0.0, 0.5, 0.3, 0.01, format="%.4f") / 100
    run = st.button("執行回測", type="primary")

stock_id = store.resolve(query)
if not stock_id:
    st.error(f"查無「{query}」")
    st.stop()

raw = store.load_bars(stock_id, final_only=True)
if raw.empty:
    st.warning("此標的無資料")
    st.stop()

name = store.load_instruments().query("stock_id == @stock_id")["name"]
name = name.iloc[0] if not name.empty else ""

if run:
    fc = S.four_color.model_copy(update={
        "red_price_lookback": red_price_lb, "red_vol_lookback": red_vol_lb,
        "red_vol_ratio": red_vol_ratio,
        "black_price_lookback": black_price_lb, "black_vol_lookback": black_vol_lb,
        "black_vol_ratio": black_vol_ratio,
    })
    bt = SingleBTConfig(initial_cash=init_cash, fee_rate=fee, tax_rate=tax)
    with st.spinner("回測中…"):
        res = run_single(raw.set_index("date"), bt, fc, adjust=True)
        summ = summarize_single(res)

    if not summ:
        st.error("資料量不足以回測")
        st.stop()

    st.subheader(f"{stock_id} {name}")
    cols = st.columns(4)
    order = ["策略總報酬", "買進持有報酬", "超額報酬", "年化報酬",
             "夏普值", "策略最大回撤", "持有最大回撤", "交易次數"]
    for i, k in enumerate(order):
        if k in summ:
            cols[i % 4].metric(k, summ[k])
    st.caption(f"勝率：{summ.get('勝率', '—')}")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=res["equity"].index, y=res["equity"].values,
                             name="四色策略", line=dict(color="#D9463F", width=2)))
    fig.add_trace(go.Scatter(x=res["benchmark"].index, y=res["benchmark"].values,
                             name="買進持有", line=dict(color="#2E6FD9", width=2)))
    fig.update_layout(title=f"{stock_id} {name} 權益曲線", height=460,
                      hovermode="x unified", yaxis_title="資產",
                      legend=dict(orientation="h", y=1.02, yanchor="bottom"))
    st.plotly_chart(fig, use_container_width=True)

    trades = [t for t in res["trades"] if "報酬" in t]
    with st.expander(f"交易明細（{len(trades)} 筆）"):
        if trades:
            tr = pd.DataFrame([{
                "進場日": t["進場日"].date(), "進場價": round(t["進場價"], 2),
                "出場日": t["出場日"].date(), "出場價": round(t["出場價"], 2),
                "報酬": f"{t['報酬']:.1%}",
            } for t in trades])
            st.dataframe(tr, use_container_width=True, hide_index=True)
            st.download_button("下載交易明細 CSV",
                               tr.to_csv(index=False).encode("utf-8-sig"),
                               f"single_bt_{stock_id}.csv", "text/csv")
else:
    st.info(f"目前標的：{stock_id} {name}。設定參數後按「執行回測」。")
    st.markdown("""
**邏輯**：四色首次轉紅 → 隔日開盤**全押**買入；轉黑 → 隔日開盤全部賣出、回到現金。
空手期間為純現金。對照為同一檔買進持有（皆用還原價、計手續費+證交稅）。

- 紅：突破前 N 日最高收盤 + 量 > 前 N 日平均量 × 倍數
- 黑：跌破前 N 日最低收盤 + 量 > 前 N 日平均量 × 倍數（紅黑各自獨立）

**怎麼看**：強勢上漲股，買進持有通常勝；震盪或轉弱股，四色擇時可能勝且回撤較小。
""")