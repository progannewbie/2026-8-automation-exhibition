"""
SmartCook 流程配置 (Phase Controller Configuration)
各菜色的流程參數、狀態機定義
"""

from enum import Enum
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# ============================================================================
# 1. 流程階段定義
# ============================================================================

class Phase(Enum):
    """流程階段列舉"""
    
    # 基本階段
    INIT = "INIT"               # 初始化
    PICKUP = "PICKUP"           # 取料
    CHOP = "CHOP"               # 切割
    PLACE = "PLACE"             # 放置
    FLIP = "FLIP"               # 翻炒
    PLACE_FINAL = "PLACE_FINAL" # 最終放盤
    HOME = "HOME"               # 復歸
    DONE = "DONE"               # 完成


class PhaseStatus(Enum):
    """階段執行狀態"""
    
    PENDING = "PENDING"         # 待執行
    RUNNING = "RUNNING"         # 執行中
    SUCCESS = "SUCCESS"         # 成功
    FAILED = "FAILED"           # 失敗
    RETRY = "RETRY"             # 重試


# ============================================================================
# 2. 食材切割參數
# ============================================================================

@dataclass
class FoodCutParams:
    """食材切割參數"""
    food_type: str              # "CUCUMBER", "ROMAINE"
    num_cuts: int               # 切割次數
    cut_thickness_mm: float     # 切割厚度 (mm)
    holding_arm: str            # 壓住食材的臂 (F60_R)
    description: str            # 說明


FOOD_CUT_PARAMS = {
    "CUCUMBER": FoodCutParams(
        food_type="CUCUMBER",
        num_cuts=5,
        cut_thickness_mm=4.0,
        holding_arm="F60_R",
        description="小黃瓜：5 片，每片 4mm",
    ),
    "ROMAINE": FoodCutParams(
        food_type="ROMAINE",
        num_cuts=8,
        cut_thickness_mm=30.0,
        holding_arm="F60_R",
        description="蘿蔓生菜：8 段，每段 30mm",
    ),
}


# ============================================================================
# 3. 翻炒參數
# ============================================================================

@dataclass
class FlipParams:
    """翻炒參數"""
    num_cycles: int             # 循環次數
    speed_percent: int          # 速度百分比 (1-100)
    duration_sec: Optional[float] # 預估時間（秒）
    description: str            # 說明


FLIP_PARAMS = {
    "standard": FlipParams(
        num_cycles=6,
        speed_percent=50,
        duration_sec=18.0,  # 約 3 秒/循環
        description="標準翻炒：6 循環，50% 速度",
    ),
    "gentle": FlipParams(
        num_cycles=8,
        speed_percent=40,
        duration_sec=24.0,
        description="溫和翻炒：8 循環，40% 速度",
    ),
    "vigorous": FlipParams(
        num_cycles=10,
        speed_percent=60,
        duration_sec=20.0,
        description="劇烈翻炒：10 循環，60% 速度",
    ),
}


# ============================================================================
# 4. 菜色流程定義
# ============================================================================

@dataclass
class PhaseInstruction:
    """單一階段指令"""
    phase: Phase                # 階段名稱
    action: str                 # 動作 (PICKUP, CHOP, PLACE, FLIP 等)
    location: str               # 位置 (PICKUP_CUCUMBER, SALAD_BOWL 等)
    params: Optional[Dict] = None  # 額外參數
    retries: int = 3            # 重試次數
    timeout_sec: float = 30.0   # 超時時間 (秒)


class MenuRecipes:
    """菜色食譜與流程"""
    
    # ========================================================================
    # 菜色 1: 小黃瓜單品
    # ========================================================================
    
    RECIPE_1_CUCUMBER = {
        "name": "菜色 1: 小黃瓜",
        "description": "取小黃瓜 → 切 → 放沙拉盤",
        "continuous": False,
        "estimated_time_sec": 35,
        "phases": [
            PhaseInstruction(
                phase=Phase.PICKUP,
                action="PICKUP",
                location="PICKUP_CUCUMBER",
                params={"arm": "F60_F"},
            ),
            PhaseInstruction(
                phase=Phase.CHOP,
                action="CHOP",
                location="WORK_CHOP_ZONE",
                params=FOOD_CUT_PARAMS["CUCUMBER"].__dict__,
            ),
            PhaseInstruction(
                phase=Phase.PLACE_FINAL,
                action="PLACE",
                location="SALAD_BOWL",
                params={"method": "POUR"},
            ),
            PhaseInstruction(
                phase=Phase.HOME,
                action="HOME",
                location="HOME_LEFT",
                params={"arm": "F60_F"},
            ),
        ],
    }
    
    # ========================================================================
    # 菜色 2: 蘿蔓生菜單品
    # ========================================================================
    
    RECIPE_2_ROMAINE = {
        "name": "菜色 2: 蘿蔓生菜",
        "description": "取生菜 → 切 → 放沙拉盤",
        "continuous": False,
        "estimated_time_sec": 40,
        "phases": [
            PhaseInstruction(
                phase=Phase.PICKUP,
                action="PICKUP",
                location="PICKUP_ROMAINE",
                params={"arm": "F60_F"},
            ),
            PhaseInstruction(
                phase=Phase.CHOP,
                action="CHOP",
                location="WORK_CHOP_ZONE",
                params=FOOD_CUT_PARAMS["ROMAINE"].__dict__,
            ),
            PhaseInstruction(
                phase=Phase.PLACE_FINAL,
                action="PLACE",
                location="SALAD_BOWL",
                params={"method": "POUR"},
            ),
            PhaseInstruction(
                phase=Phase.HOME,
                action="HOME",
                location="HOME_LEFT",
                params={"arm": "F60_F"},
            ),
        ],
    }
    
    # ========================================================================
    # 菜色 3: 紅卷須單品（不切）
    # ========================================================================
    
    RECIPE_3_RED_LEAF = {
        "name": "菜色 3: 紅卷須",
        "description": "取紅卷須 → 放沙拉盤（不切）",
        "continuous": False,
        "estimated_time_sec": 20,
        "phases": [
            PhaseInstruction(
                phase=Phase.PICKUP,
                action="PICKUP",
                location="PICKUP_RED_LEAF",
                params={"arm": "F60_F"},
            ),
            PhaseInstruction(
                phase=Phase.PLACE_FINAL,
                action="PLACE",
                location="SALAD_BOWL",
                params={"method": "POUR"},
            ),
            PhaseInstruction(
                phase=Phase.HOME,
                action="HOME",
                location="HOME_LEFT",
                params={"arm": "F60_F"},
            ),
        ],
    }
    
    # ========================================================================
    # 菜色 4: 生菜沙拉完整流程（連續執行）
    # ========================================================================
    
    RECIPE_4_SALAD = {
        "name": "菜色 4: 生菜沙拉完整流程",
        "description": "小黃瓜 → 等待區 → 生菜 → 搅拌區 → 紅卷須 → 翻炒 → 沙拉盤",
        "continuous": True,  # ⚠️ 必須連續執行
        "estimated_time_sec": 150,  # ~2.5 分鐘
        "phases": [
            # ================================================================
            # 步驟 1: 小黃瓜 → 等待區
            # ================================================================
            
            PhaseInstruction(
                phase=Phase.PICKUP,
                action="PICKUP",
                location="PICKUP_CUCUMBER",
                params={"arm": "F60_F"},
            ),
            PhaseInstruction(
                phase=Phase.CHOP,
                action="CHOP",
                location="WORK_CHOP_ZONE",
                params=FOOD_CUT_PARAMS["CUCUMBER"].__dict__,
            ),
            PhaseInstruction(
                phase=Phase.PLACE,
                action="PLACE",
                location="WAIT_ZONE",
                params={"method": "SCOOP"},
            ),
            
            # ================================================================
            # 步驟 2: 蘿蔓生菜 → 搅拌區
            # ================================================================
            
            PhaseInstruction(
                phase=Phase.PICKUP,
                action="PICKUP",
                location="PICKUP_ROMAINE",
                params={"arm": "F60_F"},
            ),
            PhaseInstruction(
                phase=Phase.CHOP,
                action="CHOP",
                location="WORK_CHOP_ZONE",
                params=FOOD_CUT_PARAMS["ROMAINE"].__dict__,
            ),
            PhaseInstruction(
                phase=Phase.PLACE,
                action="PLACE",
                location="MIX_ZONE",
                params={"method": "SCOOP"},
            ),
            
            # ================================================================
            # 步驟 3: 等待區小黃瓜 → 搅拌區
            # ================================================================
            
            PhaseInstruction(
                phase=Phase.PICKUP,
                action="PICKUP",
                location="WAIT_ZONE",
                params={"arm": "F60_F"},
            ),
            PhaseInstruction(
                phase=Phase.PLACE,
                action="PLACE",
                location="MIX_ZONE",
                params={"method": "SCOOP"},
            ),
            
            # ================================================================
            # 步驟 4: 紅卷須 → 搅拌區
            # ================================================================
            
            PhaseInstruction(
                phase=Phase.PICKUP,
                action="PICKUP",
                location="PICKUP_RED_LEAF",
                params={"arm": "F60_F"},
            ),
            PhaseInstruction(
                phase=Phase.PLACE,
                action="PLACE",
                location="MIX_ZONE",
                params={"method": "SCOOP"},
            ),
            
            # ================================================================
            # 步驟 5: 翻炒
            # ================================================================
            
            PhaseInstruction(
                phase=Phase.FLIP,
                action="FLIP",
                location="MIX_ZONE",
                params=FLIP_PARAMS["standard"].__dict__,
            ),
            
            # ================================================================
            # 步驟 6: 倒沙拉盤
            # ================================================================
            
            PhaseInstruction(
                phase=Phase.PLACE_FINAL,
                action="PLACE",
                location="SALAD_BOWL",
                params={"method": "POUR"},
            ),
            
            # ================================================================
            # 步驟 7: 復歸
            # ================================================================
            
            PhaseInstruction(
                phase=Phase.HOME,
                action="HOME",
                location="HOME_LEFT",
                params={"arm": "F60_F"},
            ),
        ],
    }


# ============================================================================
# 5. 流程狀態機轉移
# ============================================================================

# 狀態轉移規則：
#
# INIT → PICKUP → CHOP → PLACE / PLACE_FINAL
#                       ↓
#                   FLIP (可選)
#                       ↓
#                 PLACE_FINAL
#                       ↓
#                     HOME
#                       ↓
#                     DONE
PHASE_TRANSITIONS = {
    Phase.INIT: [Phase.PICKUP],
    Phase.PICKUP: [Phase.CHOP, Phase.PLACE],
    Phase.CHOP: [Phase.PLACE, Phase.PLACE_FINAL],
    Phase.PLACE: [Phase.PICKUP, Phase.FLIP, Phase.PLACE_FINAL],
    Phase.FLIP: [Phase.PLACE_FINAL],
    Phase.PLACE_FINAL: [Phase.HOME],
    Phase.HOME: [Phase.DONE],
    Phase.DONE: [],
}


# ============================================================================
# 6. 錯誤重試策略
# ============================================================================

class RetryPolicy:
    """重試策略"""
    
    MAX_RETRIES = 3
    RETRY_DELAY_SEC = 2.0
    
    # 哪些指令可重試
    RETRYABLE_ACTIONS = {
        "PICKUP",      # 重新取料
        "CHOP",        # 重新切割
        "PLACE",       # 重新放置
    }
    
    # 哪些指令不可重試（立即失敗）
    CRITICAL_ACTIONS = {
        "HOME",        # 復歸失敗 → 危險
        "STOP",        # 停止失敗 → 危險
    }


# ============================================================================
# 7. 流程監控與日誌
# ============================================================================

@dataclass
class PhaseLog:
    """階段執行日誌"""
    phase: Phase
    status: PhaseStatus
    start_time: float           # Unix 時間戳
    end_time: Optional[float]   # 完成時間
    duration_sec: Optional[float] # 執行時間
    error_msg: Optional[str]    # 錯誤信息
    retry_count: int            # 重試次數


# ============================================================================
# 8. 菜單導航
# ============================================================================

MENU = {
    "1": MenuRecipes.RECIPE_1_CUCUMBER,
    "2": MenuRecipes.RECIPE_2_ROMAINE,
    "3": MenuRecipes.RECIPE_3_RED_LEAF,
    "4": MenuRecipes.RECIPE_4_SALAD,
}


def get_recipe(choice: str) -> Optional[Dict]:
    """
    根據用戶選擇取得食譜
    
    Args:
        choice: "1", "2", "3", "4"
    
    Returns:
        食譜字典或 None
    """
    return MENU.get(choice)


def get_phases(choice: str) -> Optional[List[PhaseInstruction]]:
    """
    根據用戶選擇取得階段序列
    
    Args:
        choice: "1", "2", "3", "4"
    
    Returns:
        PhaseInstruction 列表或 None
    """
    recipe = get_recipe(choice)
    if recipe:
        return recipe.get("phases", [])
    return None

