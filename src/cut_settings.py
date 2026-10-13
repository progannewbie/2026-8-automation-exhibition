"""
使用者可調的切片厚度（網頁介面輸入，存在 src/settings/cut_thickness.json）

小黃瓜、紅蘿蔔由現場人員在介面上調；生菜固定 CHOP_STEP_MM（ROMAINE_START_INDEX 是照這個格距量的）。
CHOP 指令的 <CUT_THICKNESS_MM> 就是兩臂每刀之間移動的距離（AS DO_CHOP 用 .thick 算下刀點/壓點）。
"""

import json
import logging
import os
import threading
from typing import Dict

from config_phase import CHOP_STEP_MM

logger = logging.getLogger(__name__)

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "settings", "cut_thickness.json")

# 介面上能調的食材與預設值 (mm)
ADJUSTABLE = {
    "CUCUMBER": {"name": "小黃瓜", "default": CHOP_STEP_MM},
    "CARROT": {"name": "紅蘿蔔", "default": 7.0},
}
MIN_MM = 3.0
MAX_MM = 15.0

_lock = threading.Lock()


def _load() -> Dict[str, float]:
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {k: float(v) for k, v in data.items() if k in ADJUSTABLE}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        logger.warning(f"⚠️ 切片厚度設定檔讀不到，改用預設值: {exc}")
        return {}


def get_thickness(food_type: str) -> float:
    """這種食材現在要切多厚 (mm)。不能調的食材一律 CHOP_STEP_MM。"""
    if food_type not in ADJUSTABLE:
        return CHOP_STEP_MM
    with _lock:
        value = _load().get(food_type, ADJUSTABLE[food_type]["default"])
    return value if MIN_MM <= value <= MAX_MM else ADJUSTABLE[food_type]["default"]


def set_thickness(food_type: str, value) -> str:
    """存檔，回傳錯誤訊息；成功回空字串"""
    if food_type not in ADJUSTABLE:
        return f"{food_type} 的厚度不能調整"
    try:
        value = round(float(value), 1)
    except (TypeError, ValueError):
        return "請輸入數字"
    if not MIN_MM <= value <= MAX_MM:
        return f"厚度要在 {MIN_MM:g}～{MAX_MM:g} mm 之間"

    with _lock:
        data = _load()
        data[food_type] = value
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        tmp = SETTINGS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_PATH)
    logger.info(f"✓ {ADJUSTABLE[food_type]['name']}切片厚度設為 {value:g} mm")
    return ""


def snapshot() -> Dict:
    """給網頁介面用：每種可調食材的名稱、目前厚度與範圍（用 list 保持順序，jsonify 會排序 dict 的 key）"""
    return {
        "min": MIN_MM,
        "max": MAX_MM,
        "foods": [{"key": k, "name": v["name"], "value": get_thickness(k), "default": v["default"]}
                  for k, v in ADJUSTABLE.items()],
    }
