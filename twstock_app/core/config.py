from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
CONFIG_DIR = ROOT / "config"


class FourColorConfig(BaseModel):
    """四色 K 線參數。紅、黑各自獨立（價格回看、量能回看、量能倍數）。"""

    # === 紅（買進）===
    red_price_lookback: int = Field(5, ge=3, le=20, description="紅：突破前 N 日最高收盤")
    red_vol_lookback: int = Field(5, ge=3, le=20, description="紅：量 > 前 N 日平均量")
    red_vol_ratio: float = Field(1.30, ge=1.00, le=1.50, description="紅：量能倍數（1.0~1.5）")

    # === 黑（賣出）===
    black_price_lookback: int = Field(5, ge=3, le=20, description="黑：跌破前 N 日最低收盤")
    black_vol_lookback: int = Field(5, ge=3, le=20, description="黑：量 > 前 N 日平均量")
    black_vol_ratio: float = Field(1.30, ge=1.00, le=1.50, description="黑：量能倍數（1.0~1.5）")

    initial_color: str = Field("yellow", description="暖機結束後的起始顏色")
    persist_on_undefined: bool = Field(
        True, description="未觸發任何轉換條件時，沿用前一日顏色"
    )

    # UI 滑桿範圍
    ui_lookback_range: tuple[int, int] = (3, 20)
    ui_vol_ratio_range: tuple[float, float] = (1.00, 1.50)


class UniverseConfig(BaseModel):
    """選股池篩選門檻。"""

    min_close: float = Field(6.0, description="排除成交價低於此值的低價股")
    min_volume_lots: int = Field(100, description="排除日均量低於此值(張)的冷門股")
    volume_window: int = Field(60, description="成交量取滾動中位數的視窗（交易日）")
    min_listed_days: int = Field(60, description="排除上市未滿此天數的新股")


class MAConfig(BaseModel):
    """各週期可選的均線清單。"""

    daily: list[int] = [5, 10, 20, 60, 120, 240]
    weekly: list[int] = [5, 10, 20]
    monthly: list[int] = [5, 10, 20]
    price_max_lines: int = 3
    volume_min: int = 3
    volume_max: int = 30
    volume_max_lines: int = 2


class Settings(BaseModel):
    four_color: FourColorConfig = FourColorConfig()
    universe: UniverseConfig = UniverseConfig()
    ma: MAConfig = MAConfig()

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or CONFIG_DIR / "settings.yaml"
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            # 容錯：舊版 settings.yaml 可能還有已移除的欄位，過濾掉再載入
            if data and "four_color" in data:
                valid = set(FourColorConfig.model_fields.keys())
                data["four_color"] = {k: v for k, v in data["four_color"].items() if k in valid}
            return cls(**data)
        return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or CONFIG_DIR / "settings.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(self.model_dump(), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


# 四色 -> 繪圖色碼
COLOR_HEX = {
    "red": "#D9463F",
    "yellow": "#E8B62C",
    "blue": "#2E6FD9",
    "black": "#2B2B2B",
    "gray": "#B0B0B0",
}

VOL_UP_COLOR = "#D9463F"
VOL_DOWN_COLOR = "#2E6FD9"