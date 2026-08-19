"""回測頁：四色策略 vs 0050。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from twstock_app.core import store
from twstock_app.core.backtest import BacktestConfig, run_backtest, summarize
from twstock_app.core.config import Settings

st.set_page_config(page_title="回測", layout="wide")
st.title("四色策略回測 vs 0050")

S = Settings.load()
bars = store.load_all_bars()
if bars.empty:
    st.warning("尚無資料，請先執行 backfill.py")
    st.stop()

with st.sidebar:
    st.header("回測參數")
    init_cash = st.number_input("初始資金", 100_000, 100_000_000, 1_000_000, step=100_000)
    mode_label = st.radio("部位模式", ["固定每筆 1%", "滿倉輪動（固定檔數）"],
                          help="固定：每筆買初始資金的固定比例，可無限持有。"
                               "輪動：最多持有 N 檔，每檔=資金/N，滿了忽略新訊號直到有空位。")
    mode = "rotate" if "輪動" in mode_label else "fixed"
    if mode == "fixed":
        pct = st.slider("每筆佔初始資金 %", 0.5, 5.0, 1.0, 0.5) / 100
        max_hold = 20
    else:
        max_hold = st.slider("最多持有檔數 N", 5, 50, 20, 5)
        pct = 0.01
        st.caption(f"每檔部位 = 資金 / {max_hold} = {100/max_hold:.1f}%，滿 {max_hold} 檔滿倉")
    uni_size = st.slider("標的池大小（前 N 大市值近似）", 5, 100, 50, 5)
    st.caption("市值以成交金額 60 日均值近似（權值股相關性高）")

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

    dates = sorted(pd.to_datetime(bars["date"]).dt.date.unique())
    c1, c2 = st.columns(2)
    start = c1.date_input("起", dates[0], min_value=dates[0], max_value=dates[-1])
    end = c2.date_input("迄", dates[-1], min_value=dates[0], max_value=dates[-1])
    run = st.button("執行回測", type="primary")

if run:
    bt = BacktestConfig(
        initial_cash=init_cash, position_pct=pct, position_mode=mode,
        max_holdings=max_hold, universe_size=uni_size,
        fee_rate=fee, tax_rate=tax,
    )
    fc = S.four_color.model_copy(update={
        "red_price_lookback": red_price_lb, "red_vol_lookback": red_vol_lb,
        "red_vol_ratio": red_vol_ratio,
        "black_price_lookback": black_price_lb, "black_vol_lookback": black_vol_lb,
        "black_vol_ratio": black_vol_ratio,
    })
    with st.spinner("回測中…（掃全期間，約數秒到數十秒）"):
        res = run_backtest(bars, bt, fc, str(start), str(end))
        summ = summarize(res)

    cols = st.columns(4)
    order = ["總報酬", "0050報酬", "超額報酬", "年化報酬(CAGR)",
             "夏普值", "最大回撤", "交易次數", "勝率"]
    for i, k in enumerate(order):
        if k in summ:
            cols[i % 4].metric(k, summ[k])

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=res["equity"].index, y=res["equity"].values,
                             name="四色策略", line=dict(color="#D9463F", width=2)))
    if res["benchmark"] is not None:
        fig.add_trace(go.Scatter(x=res["benchmark"].index, y=res["benchmark"].values,
                                 name="0050 買進持有", line=dict(color="#2E6FD9", width=2)))
    fig.update_layout(title="權益曲線", height=460, hovermode="x unified",
                      yaxis_title="資產", legend=dict(orientation="h", y=1.02, yanchor="bottom"))
    st.plotly_chart(fig, use_container_width=True)

    with st.expander(f"交易明細（{len(res['trades'])} 筆）"):
        tr = pd.DataFrame([{
            "代號": t.stock_id, "進場日": t.entry_date.date(), "進場價": round(t.entry_price, 2),
            "出場日": t.exit_date.date() if t.exit_date else "持有中",
            "出場價": round(t.exit_price, 2) if t.exit_price else "-",
            "報酬": f"{t.ret:.1%}" if t.exit_date else "-",
        } for t in res["trades"]])
        st.dataframe(tr, use_container_width=True, hide_index=True)
        if not tr.empty:
            st.download_button("下載交易明細 CSV",
                               tr.to_csv(index=False).encode("utf-8-sig"),
                               "backtest_trades.csv", "text/csv")
else:
    st.info("設定左側參數後，按「執行回測」。")
    st.markdown("""
**策略邏輯**
- 標的池：每日成交金額前 N 大（近似 0050 權值股，逐日重算避免前視偏差）
- 進場：標的在池內、四色**首次轉紅** → **隔日開盤**買入
- 出場：持有中標的四色**轉黑** → **隔日開盤**賣出
- 紅：突破前 N 日最高收盤 + 量 > 前 N 日平均量 × 倍數
- 黑：跌破前 N 日最低收盤 + 量 > 前 N 日平均量 × 倍數（紅黑各自獨立）
- 計手續費 + 證交稅；對照：買進持有 0050
""")