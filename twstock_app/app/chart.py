from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ..core.config import COLOR_HEX, VOL_DOWN_COLOR, VOL_UP_COLOR

CLASSIC = {"red": "#D9463F", "green": "#26A69A", "blue": "#2E6FD9"}


def _auto_tick(n_bars: int, freq: str) -> dict:
    if freq == "monthly":
        return {"dtick": "M3", "tickformat": "%Y/%m"}
    if freq == "weekly":
        return {"dtick": "M1" if n_bars > 60 else "M1", "tickformat": "%Y/%m"}
    if n_bars > 240:
        return {"dtick": "M2", "tickformat": "%Y/%m"}
    if n_bars > 120:
        return {"dtick": "M1", "tickformat": "%Y/%m"}
    if n_bars > 40:
        return {"dtick": 7 * 86400000, "tickformat": "%m/%d"}
    return {"dtick": 86400000 * 2, "tickformat": "%m/%d"}


def build_chart(
    df: pd.DataFrame,
    colors: pd.Series | None,
    price_ma: list[int],
    vol_ma: list[int],
    freq: str,
    mode: str = "four_color",   # four_color | classic_rg | classic_rb
    title: str = "",
) -> go.Figure:
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.72, 0.28], vertical_spacing=0.03,
    )

    if mode == "four_color" and colors is not None:
        for name, hex_ in COLOR_HEX.items():
            m = (colors == name).to_numpy()
            if not m.any():
                continue
            sub = df[m]
            fig.add_trace(
                go.Candlestick(
                    x=sub.index, open=sub.open, high=sub.high, low=sub.low, close=sub.close,
                    increasing=dict(line=dict(color=hex_), fillcolor=hex_),
                    decreasing=dict(line=dict(color=hex_), fillcolor=hex_),
                    name=name, showlegend=True,
                ), row=1, col=1,
            )
    else:
        up = CLASSIC["red"]
        dn = CLASSIC["green"] if mode == "classic_rg" else CLASSIC["blue"]
        fig.add_trace(
            go.Candlestick(
                x=df.index, open=df.open, high=df.high, low=df.low, close=df.close,
                increasing=dict(line=dict(color=up), fillcolor=up),
                decreasing=dict(line=dict(color=dn), fillcolor="rgba(0,0,0,0)"),
                name="K", showlegend=False,
            ), row=1, col=1,
        )

    for w in price_ma:
        col = f"ma{w}"
        if col in df:
            fig.add_trace(
                go.Scatter(x=df.index, y=df[col], mode="lines", name=f"MA{w}",
                           line=dict(width=1.2)),
                row=1, col=1,
            )

    vol_colors = np.where(df.close >= df.open, VOL_UP_COLOR, VOL_DOWN_COLOR)
    fig.add_trace(
        go.Bar(x=df.index, y=df.volume, marker_color=vol_colors,
               name="成交量", showlegend=False),
        row=2, col=1,
    )
    for w in vol_ma:
        col = f"vma{w}"
        if col in df:
            fig.add_trace(
                go.Scatter(x=df.index, y=df[col], mode="lines", name=f"VMA{w}",
                           line=dict(width=1.2)),
                row=2, col=1,
            )

    tick = _auto_tick(len(df), freq)
    fig.update_xaxes(rangeslider_visible=False, **tick, row=1, col=1)
    fig.update_xaxes(rangeslider_visible=False, **tick, row=2, col=1)
    if freq == "daily":
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

    fig.update_yaxes(title_text="價格", row=1, col=1)
    fig.update_yaxes(title_text="成交量(張)", row=2, col=1)
    fig.update_layout(
        title=title, height=720, margin=dict(l=50, r=20, t=50, b=30),
        hovermode="x unified", legend=dict(orientation="h", y=1.02, yanchor="bottom"),
    )
    return fig