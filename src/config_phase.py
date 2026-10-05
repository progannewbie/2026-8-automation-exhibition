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
    MEASURE = "MEASURE"         # 視覺量測（切割前量食材位置，不動手臂）
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


# ⚠️ 切片厚度由左臂下刀點決定，cut_thickness_mm 改了沒有作用。
#
#    第 i 格的下刀點 = chop_1[1] 沿 X 往後 (i-1)×5mm（左臂 AS 即時計算，跟教點陣列
#    chop_1[1..30] 的值相同，但可以算到第 60 格）。.thick 只拿來檢查 > 0。
#
# ⚠️ 右臂跟著刀走：每一刀都是「右臂在離下刀處 10mm 的地方壓好 → 左臂切 → 右臂抬起」，
#    下一刀兩臂一起往後移 5mm。右臂第 i 格壓點 = press_chop_zone 沿右臂 X 移
#    (i-1)×5mm×press_dir（右臂 INIT_CONST）。press_chop_zone 要教在離 chop_1[1]
#    下刀處 10mm、還沒切的那一側。
#
# ⚠️ AS 端 DO_CHOP：刀數 1～60，最後一刀的格數 (起始格 + 刀數 - 1) 不超過 60。

CHOP_STEP_MM = 5.0   # 必須等於左臂下刀點的間距（chop_1[] 教點陣列的間距）

# CHOP 等手臂回應的秒數。2026-09-21 實測 15 刀約 28 秒（當時右臂只壓一次）；
# 現在每刀都要等右臂抬起、移動、壓好，整根最多 60 刀，抓 300 秒。
# 逾時會停用連線、整道菜中止（不會重送）。第一次實機後依實際時間調整。
CHOP_TIMEOUT_SEC = 300.0


class ChopPlanConfig:
    """
    小黃瓜 / 紅蘿蔔「整根切完」與生菜下刀位置的參數

    流程：送進切割區 → MEASURE 拍照量出食材兩端在左臂座標的 X →
    算出起始格與刀數 → CHOP,<食材>,<刀數>,5.0,<起始格>

        起始格   = X 小那端 + TIP_OFFSET_MM 落在第幾格
        最後一刀 = X 大那端 - TAIL_MARGIN_MM 之前的最後一格

    ⚠️ 切割區還沒標定（config_vision.ChopZoneHomography 沒有 H）時不量測，
       照舊「從第 1 格切 FOOD_CUT_PARAMS 的刀數」。
    """

    # 左臂 GBK 版 chop_1[1] 的 X（教點表 chop_1[1] 308.854706 ...）。重教點後要跟著改。
    CHOP_1_FIRST_X_MM = 308.854706
    MAX_CUTS = 60
    MAX_INDEX = 60               # 最後一刀的格數上限（AS 端同一個值）

    TIP_OFFSET_MM = 5.0          # 第一刀落在 X 小那端往內幾 mm（= 第一片的厚度）
    TAIL_MARGIN_MM = 5.0         # 最後一刀至少離 X 大那端幾 mm（避免切到空氣）

    MIN_LENGTH_MM = 30.0         # 比這短當成量錯
    MAX_AXIS_ANGLE_DEG = 15.0    # 食材軸線跟刀子行進方向 (左臂 X 軸) 的夾角上限

    # 生菜「中間切一刀」落在第幾格（第 i 格 = chop_1[1] 往後 (i-1)×5mm）。
    # 待現場量測：用 test/chop_points.py ROMAINE --start N 預覽、教導器對點後填入。
    # None = 還沒量 → 生菜不切，CHOP 階段直接失敗。
    ROMAINE_START_INDEX: Optional[int] = None

    @classmethod
    def cut_x(cls, index: int) -> float:
        return cls.CHOP_1_FIRST_X_MM + (index - 1) * CHOP_STEP_MM

    @classmethod
    def plan(cls, low_x_mm: float, high_x_mm: float) -> Tuple[Optional[Dict], str]:
        """
        依食材兩端的左臂 X 算出 {"start", "cuts"}

        Returns:
            (計畫, 說明)。計畫是 None 表示不能切，說明裡寫原因。
        """
        step = CHOP_STEP_MM
        first = (low_x_mm + cls.TIP_OFFSET_MM - cls.CHOP_1_FIRST_X_MM) / step + 1
        start = int(round(first))
        if start < 1:
            if start >= 0:
                start = 1   # 差一格以內就從第 1 格切（第一片稍厚）
            else:
                return None, (f"食材前端超出切割範圍 {1 - first:.0f} 格"
                              f"（約 {(1 - first) * step:.0f}mm），請往後放")

        last = int((high_x_mm - cls.TAIL_MARGIN_MM - cls.CHOP_1_FIRST_X_MM) // step) + 1
        cuts = last - start + 1
        if cuts < 1:
            return None, f"量到的長度太短，切不到任何一刀（X {low_x_mm:.0f}～{high_x_mm:.0f}）"
        if cuts > cls.MAX_CUTS or last > cls.MAX_INDEX:
            return None, (f"要切第 {start}～{last} 格共 {cuts} 刀，"
                          f"超過上限（{cls.MAX_CUTS} 刀、第 {cls.MAX_INDEX} 格）")

        return {"start": start, "cuts": cuts}, f"從第 {start} 格切到第 {last} 格，共 {cuts} 刀"


FOOD_CUT_PARAMS = {
    "CUCUMBER": FoodCutParams(
        food_type="CUCUMBER",
        num_cuts=15,
        cut_thickness_mm=CHOP_STEP_MM,
        holding_arm="F60_R",
        description="小黃瓜：整根切完（MEASURE 量長度決定刀數）；量不到時從第 1 格切 15 刀",
    ),
    "CARROT": FoodCutParams(
        food_type="CARROT",
        num_cuts=15,
        cut_thickness_mm=CHOP_STEP_MM,
        holding_arm="F60_R",
        description="紅蘿蔔：整根切完（MEASURE 量長度決定刀數）；量不到時從第 1 格切 15 刀",
    ),
    "ROMAINE": FoodCutParams(
        food_type="ROMAINE",
        num_cuts=1,
        cut_thickness_mm=25.0,
        holding_arm="F60_R",
        # 下刀位置 = ChopPlanConfig.ROMAINE_START_INDEX（待現場量測）
        description="羅曼生菜：中間切 1 刀（葉菜易碎，不做多刀分段）",
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
        num_cycles=1,
        speed_percent=50,
        duration_sec=6.0,  # 約 3 秒/循環
        description="標準翻炒：1 循環，50% 速度",
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
    retries: int = 3            # 重試次數（只在兩臂都回 BUSY 或視覺沒偵測到時才會用到，見 PhaseController._send_motion）
    timeout_sec: float = 120.0   # 等手臂回應的秒數（9/21 實測 PLACE 約 20 秒、FLIP 約 85 秒）。逾時會停用連線、整道菜中止，不會重送


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
            # 量小黃瓜兩端位置，決定起始格、刀數、換壓點（不動手臂）
            PhaseInstruction(
                phase=Phase.MEASURE,
                action="MEASURE",
                location="WORK_CHOP_ZONE",
                params={"food_type": "CUCUMBER"},
            ),
            PhaseInstruction(
                phase=Phase.CHOP,
                action="CHOP",
                location="WORK_CHOP_ZONE",
                params=FOOD_CUT_PARAMS["CUCUMBER"].__dict__,
                timeout_sec=CHOP_TIMEOUT_SEC,
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
            # 量紅蘿蔔兩端位置，決定起始格、刀數、換壓點（不動手臂）
            PhaseInstruction(
                phase=Phase.MEASURE,
                action="MEASURE",
                location="WORK_CHOP_ZONE",
                params={"food_type": "CARROT"},
            ),
            PhaseInstruction(
                phase=Phase.CHOP,
                action="CHOP",
                location="WORK_CHOP_ZONE",
                params=FOOD_CUT_PARAMS["CARROT"].__dict__,
                timeout_sec=CHOP_TIMEOUT_SEC,
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
    RECIPE_3_ROMAINE = {
        "name": "菜色 3: 羅曼生菜",
        "description": "取羅曼生菜 → 送進切割區 → 中間切一刀 → 夾起 → 倒沙拉盤",
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
                phase=Phase.PLACE,
                action="PLACE",
                location="WORK_CHOP_ZONE",
                params={"source": "PICKUP_ROMAINE", "method": "SCOOP"},
            ),
            PhaseInstruction(
                phase=Phase.CHOP,
                action="CHOP",
                location="WORK_CHOP_ZONE",
                params=FOOD_CUT_PARAMS["ROMAINE"].__dict__,
                timeout_sec=CHOP_TIMEOUT_SEC,
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
    # 菜色 4: 生菜沙拉完整流程（連續執行）
    # ========================================================================
    # 三種食材依序各自「夾起 → 送切割區 → 切 → 夾起 → 倒沙拉盤」。
    # 不使用等待區、不翻炒混拌：每切完一種就倒進沙拉盤，把切割區清空給下一種。

    RECIPE_4_SALAD = {
        "name": "菜色 4: 生菜沙拉完整流程",
        "description": "小黃瓜 → 紅蘿蔔 → 生菜，各自切好直接倒進沙拉盤",
        "continuous": True,  # ⚠️ 必須連續執行
        "estimated_time_sec": 150,
        "phases": [
            # ================================================================
            # 步驟 1-5: 小黃瓜 → 切割區 → 切 → 夾起 → 倒沙拉盤（還有下一個食材，用 PLACE（狀態機 PLACE_FINAL 之後只能 HOME））
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
            # 量小黃瓜兩端位置，決定起始格、刀數、換壓點（不動手臂）
            PhaseInstruction(
                phase=Phase.MEASURE,
                action="MEASURE",
                location="WORK_CHOP_ZONE",
                params={"food_type": "CUCUMBER"},
            ),
            PhaseInstruction(
                phase=Phase.CHOP,
                action="CHOP",
                location="WORK_CHOP_ZONE",
                params=FOOD_CUT_PARAMS["CUCUMBER"].__dict__,
                timeout_sec=CHOP_TIMEOUT_SEC,
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
                location="SALAD_BOWL",
                params={"source": "MIX_ZONE", "method": "POUR"},
            ),

            # ================================================================
            # 步驟 6-10: 紅蘿蔔 → 切割區 → 切 → 夾起 → 倒沙拉盤（還有下一個食材，用 PLACE（狀態機 PLACE_FINAL 之後只能 HOME））
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
            # 量紅蘿蔔兩端位置，決定起始格、刀數、換壓點（不動手臂）
            PhaseInstruction(
                phase=Phase.MEASURE,
                action="MEASURE",
                location="WORK_CHOP_ZONE",
                params={"food_type": "CARROT"},
            ),
            PhaseInstruction(
                phase=Phase.CHOP,
                action="CHOP",
                location="WORK_CHOP_ZONE",
                params=FOOD_CUT_PARAMS["CARROT"].__dict__,
                timeout_sec=CHOP_TIMEOUT_SEC,
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
                location="SALAD_BOWL",
                params={"source": "MIX_ZONE", "method": "POUR"},
            ),

            # ================================================================
            # 步驟 11-15: 羅曼生菜（中間切一刀） → 切割區 → 切 → 夾起 → 倒沙拉盤（最後一個，用 PLACE_FINAL 接 HOME）
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
                location="WORK_CHOP_ZONE",
                params={"source": "PICKUP_ROMAINE", "method": "SCOOP"},
            ),
            PhaseInstruction(
                phase=Phase.CHOP,
                action="CHOP",
                location="WORK_CHOP_ZONE",
                params=FOOD_CUT_PARAMS["ROMAINE"].__dict__,
                timeout_sec=CHOP_TIMEOUT_SEC,
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
#   INIT → PICKUP → PLACE →─┬─→ (MEASURE →) CHOP → PICKUP → PLACE ...
#                           │                      ↓
#                           └──────────────→ FLIP → PICKUP → PLACE_FINAL
#                                                                 ↓
#                                                               HOME → DONE
PHASE_TRANSITIONS = {
    Phase.INIT: [Phase.PICKUP],
    Phase.PICKUP: [Phase.PLACE, Phase.PLACE_FINAL],
    Phase.PLACE: [Phase.MEASURE, Phase.CHOP, Phase.PICKUP, Phase.FLIP],
    Phase.MEASURE: [Phase.CHOP],
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
    
    # 動作指令（PICKUP / CHOP / PLACE / FLIP）只有在「兩臂都回 BUSY」時才重送，
    # 那代表兩臂都沒動。逾時、ERROR、一邊 OK 一邊失敗都不重送，因為手臂可能
    # 已經動過，重送會讓它重做一次。見 PhaseController._send_motion。
    
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

