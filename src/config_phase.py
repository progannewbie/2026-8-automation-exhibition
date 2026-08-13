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
    food_type: str              # "CUCUMBER", "CARROT", "ROMAINE"
    num_cuts: int               # 切割次數
    cut_thickness_mm: float     # 切割厚度 (mm)
    holding_arm: str            # 壓住食材的臂 (F60_R)
    description: str            # 說明


# ⚠️ cut_thickness_mm 一定要是 5.0，改別的值兩臂會走不同步。
#
#    左臂 DO_CHOP 的下刀位置是「絕對教點陣列」chop_1[i] / chop_per[i]，
#    31 個點、固定 5.0mm 間距、總跨距 150mm。迴圈裡那句 DRAW .thick,0,0
#    下一圈馬上被 LMOVE chop_per[i] 這個絕對點蓋掉，所以 .thick 對左臂
#    完全沒有作用——切割位置是教點決定的，不是參數決定的。
#
#    但右臂 DO_CHOP 沒有絕對點，整段就是靠 DRAW .thick,0,0 累加步進。
#    .thick 一旦不等於教點間距，兩臂每切一刀就多分開一點：
#        .thick=11.3 時第 15 刀左臂在 +70mm、右臂在 +158mm，差 88mm，
#        右臂等於壓在離刀子很遠的地方，完全沒壓到食材。
#
#    要改切片厚度只能重教 chop_1[] / chop_per[] 的間距，改這裡沒用。
#
#        刀刃行程 = num_cuts × 5.0mm
#
# ⚠️ AS 端 DO_CHOP 擋掉 cuts > 20，所以現況一次最多切 100mm。

CHOP_STEP_MM = 5.0   # 必須等於左臂 chop_1[] 教點陣列的間距

FOOD_CUT_PARAMS = {
    "CUCUMBER": FoodCutParams(
        food_type="CUCUMBER",
        num_cuts=15,
        cut_thickness_mm=CHOP_STEP_MM,
        holding_arm="F60_R",
        description="小黃瓜：15 刀 × 5mm，切前段 75mm（食材本身 170mm，尾段不切）",
    ),
    "CARROT": FoodCutParams(
        food_type="CARROT",
        num_cuts=15,
        cut_thickness_mm=CHOP_STEP_MM,
        holding_arm="F60_R",
        description="紅蘿蔔：15 刀 × 5mm，切前段 75mm（食材本身 170mm，尾段不切）",
    ),
    "ROMAINE": FoodCutParams(
        food_type="ROMAINE",
        num_cuts=1,
        cut_thickness_mm=25.0,
        holding_arm="F60_R",
        description="羅曼生菜：只切 1 刀（葉菜易碎，不做多刀分段）",
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
    """
    菜色食譜與流程

    ⚠️ 搬運一律是 PICKUP + PLACE 一對
       AS 的 DO_PICKUP 只負責「雙臂夾起食材」，DO_PLACE 只負責「搬到目的地放下」。
       DO_PICKUP 舊版有「階段 5：移動至切割區」會自己搬過去，現行版本已移除，
       所以每次移動食材都要先 PICKUP 夾起、再 PLACE 放下，不能只下一句 PLACE。

    ⚠️ DO_PLACE 完全不使用 source 參數
       AS 端只看 location，source 僅供 PC 端閱讀與紀錄用。因此「從 A 搬到 B」
       必須寫成 PICKUP(A) + PLACE(B) 兩步，不能靠 PLACE 的 source 指定來源。

    ⚠️ 切割區與混拌區是同一個座標
       教點 work_zone 與 mix_zone 實測差 0.005mm，是同一個物理位置。所以：
       - 切完後要夾起食材，用 PICKUP(MIX_ZONE)（DO_PICKUP 沒有 WORK_CHOP_ZONE 分支）
       - 最後一個切的食材切完不必搬，原地就是混拌區
    """

    # ========================================================================
    # 菜色 1: 小黃瓜單品
    # ========================================================================

    RECIPE_1_CUCUMBER = {
        "name": "菜色 1: 小黃瓜",
        "description": "取小黃瓜 → 送進切割區 → 切 → 夾起 → 倒沙拉盤",
        "continuous": False,
        "estimated_time_sec": 50,
        "phases": [
            PhaseInstruction(
                phase=Phase.PICKUP,
                action="PICKUP",
                location="PICKUP_CUCUMBER",
                params={"arm": "F60_F"},
            ),
            PhaseInstruction(
                phase=Phase.PLACE,
                action="PLACE",
                location="WORK_CHOP_ZONE",
                params={"source": "PICKUP_CUCUMBER", "method": "SCOOP"},
            ),
            PhaseInstruction(
                phase=Phase.CHOP,
                action="CHOP",
                location="WORK_CHOP_ZONE",
                params=FOOD_CUT_PARAMS["CUCUMBER"].__dict__,
            ),
            # 切完食材是躺在檯面上的，要先夾起來才能搬
            PhaseInstruction(
                phase=Phase.PICKUP,
                action="PICKUP",
                location="MIX_ZONE",
                params={"arm": "F60_F"},
            ),
            PhaseInstruction(
                phase=Phase.PLACE_FINAL,
                action="PLACE",
                location="SALAD_BOWL",
                params={"source": "MIX_ZONE", "method": "POUR"},
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
    # 菜色 2: 紅蘿蔔單品
    # ========================================================================

    RECIPE_2_CARROT = {
        "name": "菜色 2: 紅蘿蔔",
        "description": "取紅蘿蔔 → 送進切割區 → 切 → 夾起 → 倒沙拉盤",
        "continuous": False,
        "estimated_time_sec": 50,
        "phases": [
            PhaseInstruction(
                phase=Phase.PICKUP,
                action="PICKUP",
                location="PICKUP_CARROT",
                params={"arm": "F60_F"},
            ),
            PhaseInstruction(
                phase=Phase.PLACE,
                action="PLACE",
                location="WORK_CHOP_ZONE",
                params={"source": "PICKUP_CARROT", "method": "SCOOP"},
            ),
            PhaseInstruction(
                phase=Phase.CHOP,
                action="CHOP",
                location="WORK_CHOP_ZONE",
                params=FOOD_CUT_PARAMS["CARROT"].__dict__,
            ),
            PhaseInstruction(
                phase=Phase.PICKUP,
                action="PICKUP",
                location="MIX_ZONE",
                params={"arm": "F60_F"},
            ),
            PhaseInstruction(
                phase=Phase.PLACE_FINAL,
                action="PLACE",
                location="SALAD_BOWL",
                params={"source": "MIX_ZONE", "method": "POUR"},
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
    # 菜色 3: 羅曼生菜單品
    # ========================================================================
    # ⚠️ 生菜不切：AS 的 DO_CHOP 只認得 CUCUMBER / CARROT，
    #    送 ROMAINE 進去會落到 SCASE 的 ANY 分支回 ERROR,E4005。
    #    夾起來之後直接倒進沙拉盤。

    RECIPE_3_ROMAINE = {
        "name": "菜色 3: 羅曼生菜",
        "description": "取羅曼生菜 → 直接倒沙拉盤（葉菜不切）",
        "continuous": False,
        "estimated_time_sec": 25,
        "phases": [
            PhaseInstruction(
                phase=Phase.PICKUP,
                action="PICKUP",
                location="PICKUP_ROMAINE",
                params={"arm": "F60_F"},
            ),
            PhaseInstruction(
                phase=Phase.PLACE_FINAL,
                action="PLACE",
                location="SALAD_BOWL",
                params={"source": "PICKUP_ROMAINE", "method": "POUR"},
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
        "description": "小黃瓜→暫放 → 紅蘿蔔→留在混拌區 → 生菜→混拌區 → 取回小黃瓜 → 翻炒 → 沙拉盤",
        "continuous": True,  # ⚠️ 必須連續執行
        "estimated_time_sec": 180,
        "phases": [
            # ================================================================
            # 步驟 1-5: 小黃瓜 → 切 → 夾起 → 暫放等待區1
            # 小黃瓜必須搬走，把切割區讓給紅蘿蔔
            # ================================================================

            PhaseInstruction(
                phase=Phase.PICKUP,
                action="PICKUP",
                location="PICKUP_CUCUMBER",
                params={"arm": "F60_F"},
            ),
            PhaseInstruction(
                phase=Phase.PLACE,
                action="PLACE",
                location="WORK_CHOP_ZONE",
                params={"source": "PICKUP_CUCUMBER", "method": "SCOOP"},
            ),
            PhaseInstruction(
                phase=Phase.CHOP,
                action="CHOP",
                location="WORK_CHOP_ZONE",
                params=FOOD_CUT_PARAMS["CUCUMBER"].__dict__,
            ),
            PhaseInstruction(
                phase=Phase.PICKUP,
                action="PICKUP",
                location="MIX_ZONE",
                params={"arm": "F60_F"},
            ),
            PhaseInstruction(
                phase=Phase.PLACE,
                action="PLACE",
                location="WAIT_ZONE_1",
                params={"source": "MIX_ZONE", "method": "SCOOP"},
            ),

            # ================================================================
            # 步驟 6-8: 紅蘿蔔 → 切
            # 紅蘿蔔是最後一個切的，切完留在原地就已經在混拌區，不必搬
            # ================================================================

            PhaseInstruction(
                phase=Phase.PICKUP,
                action="PICKUP",
                location="PICKUP_CARROT",
                params={"arm": "F60_F"},
            ),
            PhaseInstruction(
                phase=Phase.PLACE,
                action="PLACE",
                location="WORK_CHOP_ZONE",
                params={"source": "PICKUP_CARROT", "method": "SCOOP"},
            ),
            PhaseInstruction(
                phase=Phase.CHOP,
                action="CHOP",
                location="WORK_CHOP_ZONE",
                params=FOOD_CUT_PARAMS["CARROT"].__dict__,
            ),

            # ================================================================
            # 步驟 9-10: 羅曼生菜 → 直接進混拌區（不切）
            # ================================================================

            PhaseInstruction(
                phase=Phase.PICKUP,
                action="PICKUP",
                location="PICKUP_ROMAINE",
                params={"arm": "F60_F"},
            ),
            PhaseInstruction(
                phase=Phase.PLACE,
                action="PLACE",
                location="MIX_ZONE",
                params={"source": "PICKUP_ROMAINE", "method": "SCOOP"},
            ),

            # ================================================================
            # 步驟 11-12: 取回等待區的小黃瓜 → 混拌區
            # DO_PICKUP 的分支名稱是 WAIT_ZONE（不是 WAIT_ZONE_1）
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
                params={"source": "WAIT_ZONE", "method": "SCOOP"},
            ),

            # ================================================================
            # 步驟 13: 翻炒
            # ================================================================

            PhaseInstruction(
                phase=Phase.FLIP,
                action="FLIP",
                location="MIX_ZONE",
                params=FLIP_PARAMS["standard"].__dict__,
            ),

            # ================================================================
            # 步驟 14-15: 夾起拌好的沙拉 → 倒沙拉盤
            # 翻炒完沙拉躺在混拌區，跟切完一樣要先夾起來
            # ================================================================

            PhaseInstruction(
                phase=Phase.PICKUP,
                action="PICKUP",
                location="MIX_ZONE",
                params={"arm": "F60_F"},
            ),
            PhaseInstruction(
                phase=Phase.PLACE_FINAL,
                action="PLACE",
                location="SALAD_BOWL",
                params={"source": "MIX_ZONE", "method": "POUR"},
            ),

            # ================================================================
            # 步驟 16: 復歸
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
# 搬運一律成對：PICKUP 夾起 → PLACE 放下。CHOP / FLIP 結束後食材是躺在
# 檯面上的，要再 PICKUP 夾起來才能搬走，所以 CHOP 和 FLIP 的下一步是 PICKUP。
#
#   INIT → PICKUP → PLACE →─┬─→ CHOP → PICKUP → PLACE ...
#                           │                      ↓
#                           └──────────────→ FLIP → PICKUP → PLACE_FINAL
#                                                                 ↓
#                                                               HOME → DONE
PHASE_TRANSITIONS = {
    Phase.INIT: [Phase.PICKUP],
    Phase.PICKUP: [Phase.PLACE, Phase.PLACE_FINAL],
    Phase.PLACE: [Phase.CHOP, Phase.PICKUP, Phase.FLIP],
    Phase.CHOP: [Phase.PICKUP],
    Phase.FLIP: [Phase.PICKUP],
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
    "2": MenuRecipes.RECIPE_2_CARROT,
    "3": MenuRecipes.RECIPE_3_ROMAINE,
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

