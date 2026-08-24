
## 安裝與執行

```bash
pip install -r requirements.txt
python scripts/run_close.py          
streamlit run twstock_app/app/main.py
```

## 排程

```cron
30 11 * * 1-5   cd /path/tw_stock && python scripts/run_intraday.py   # 盤中快照 is_final=False
0  19 * * 1-5   cd /path/tw_stock && python scripts/run_close.py      # 收盤定版 is_final=True，覆蓋 11:30
```

## 四色 K 線定義（config/settings.yaml 可調）

```
ma       = close.shift(1).rolling(lookback).mean()   # 預設 5，可調 5~10
red_px   = close >= ma
black_px = close <  ma
vol_ok   = volume > volume.shift(1) * vol_ratio      # 預設 1.30，可調 1.10~1.50
```

| 條件 | 顏色 |
|---|---|
| `red_px and vol_ok` | 🔴 紅（買進訊號） |
| `black_px and vol_ok` | ⚫ 黑（賣出訊號） |
| 前為紅，未續紅 | 🔵 藍（若 black_px）／🟡 黃 |
| 前為黑，未續黑 | 🟡 黃（若 red_px）／🔵 藍 |
| 前為黃 | 🔵 藍（若 black_px）／維持 🟡 |
| 前為藍 | 🟡 黃（若 red_px）／維持 🔵 |

**紅與黑是訊號色，每一根都必須重新滿足條件，不會黏著。** 量能不足即降級為黃/藍。

## 目錄

```
twstock_app/
  ingest/sources.py    官方 API 擷取（收盤 / 盤中 / 除權息）
  core/config.py       所有可調參數（pydantic → sidebar 自動生成）
  core/store.py        Parquet upsert / 代號名稱查詢
  core/transform.py    還原權值、週月重取樣、均線
  core/four_color.py   ★ 四色狀態機
  core/universe.py     選股池（價 > 6、滾動 60 日中位量 >= 100 張）
  app/main.py          Streamlit 介面
  app/chart.py         Plotly K 線 + 成交量 + 自動間距
```