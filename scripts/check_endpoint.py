
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twstock_app.ingest.sources import TWSE_DIVIDEND, _get

print("=" * 60)
print("1) 除權息端點目前回傳內容（前 300 字）")
print("=" * 60)
try:
    r = _get(TWSE_DIVIDEND)
    print("HTTP", r.status_code, "| Content-Type:", r.headers.get("content-type"))
    print(r.text[:300])
except Exception as e:
    print("錯誤:", e)

print()
print("=" * 60)
print("2) TWSE OpenAPI 全部端點中，名稱含 Dividend / 除權息 的")
print("=" * 60)
try:
    swagger = _get("https://openapi.twse.com.tw/v1/swagger.json").json()
    for path, spec in swagger.get("paths", {}).items():
        summary = ""
        for method in spec.values():
            summary = method.get("summary", "") or method.get("description", "")
            break
        if any(k in (path + summary) for k in ("Dividend", "除權", "除息", "TWT49")):
            print(f"  {path}")
            print(f"      {summary}")
except Exception as e:
    print("無法取得端點清單:", e)