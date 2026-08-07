"""
SmartCook 指令定義配置 (Command Definitions Configuration)
PC → F60 的所有 CSV 指令格式與參數
"""

from enum import Enum
from typing import Dict, List, Optional, Tuple

# ============================================================================
# 1. 指令類型定義 (CommandType)
# ============================================================================

class CommandType(Enum):
    """指令類型列舉"""
    
    # 動作指令
    PICKUP = "PICKUP"              # 取料
    CHOP = "CHOP"                  # 切割
    PLACE = "PLACE"                # 放置
    FLIP = "FLIP"                  # 翻炒
    
    # 控制指令
    HOME = "HOME"                  # 回到復歸點
    STOP = "STOP"                  # 緊急停止
    RESET = "RESET"                # 重置
    
    # 查詢指令
    STATUS = "STATUS"              # 查詢狀態
    READY = "READY"                # 查詢就緒狀態


# ============================================================================
# 2. 食材取料指令 (PICKUP)
# ============================================================================

class PickupCommand:
    """
    取料指令格式

    CSV: PICKUP,<LOCATION>,<ARM>,<X_MM>,<Y_MM>,<ANGLE_DEG>

    X_MM/Y_MM/ANGLE_DEG 只有 VISION_LOCATIONS（食材點位）會被 AS 端拿來用
    （即時算出 ORIGIN + TRANS(x,y,0,0,0,angle) 作為抓取點）；WAIT_ZONE 這類
    固定暫存區 AS 端會忽略這三個欄位、直接用教點，呼叫端仍要照格式帶上
    （沒有視覺目標時傳 0,0,0 即可），避免 AS 端 SPLIT_CSV 少切到欄位。

    例子:
        PICKUP,PICKUP_CUCUMBER,F60_F,120.50,80.30,45.00
        PICKUP,WAIT_ZONE,F60_F,0,0,0
    """

    FORMAT = "PICKUP,<LOCATION>,<ARM>,<X_MM>,<Y_MM>,<ANGLE_DEG>"

    VALID_LOCATIONS = [
        "PICKUP_CUCUMBER",
        "PICKUP_CARROT",
        "PICKUP_ROMAINE",
        "WAIT_ZONE",  # 菜色 4 完整流程：從等待區取回暫放的食材
    ]

    # 這幾個位置的座標由 YOLO + 手眼標定即時算出；其餘位置忽略 X/Y/ANGLE，用教點
    VISION_LOCATIONS = [
        "PICKUP_CUCUMBER",
        "PICKUP_CARROT",
        "PICKUP_ROMAINE",
    ]

    VALID_ARMS = ["F60_F", "F60_R"]  # 通常 F60_F(左臂) 取料

    @staticmethod
    def create(
        location: str,
        arm: str = "F60_F",
        x_mm: float = 0.0,
        y_mm: float = 0.0,
        angle_deg: float = 0.0,
    ) -> str:
        """建立取料指令"""
        return f"PICKUP,{location},{arm},{x_mm:.2f},{y_mm:.2f},{angle_deg:.2f}"


# ============================================================================
# 3. 切割指令 (CHOP)
# ============================================================================

class ChopCommand:
    """
    切割指令格式
    
    CSV: CHOP,<FOOD_TYPE>,<NUM_CUTS>,<CUT_THICKNESS_MM>

    例子:
        CHOP,CUCUMBER,5,4
        CHOP,CARROT,5,4
        CHOP,ROMAINE,1,25
    """

    FORMAT = "CHOP,<FOOD_TYPE>,<NUM_CUTS>,<CUT_THICKNESS_MM>"

    FOOD_TYPES = {
        "CUCUMBER": {
            "name": "小黃瓜",
            "method": "SLICE",
            "default_thickness_mm": 4,
            "typical_cuts": "5",
        },
        "CARROT": {
            "name": "紅蘿蔔",
            "method": "SLICE",
            "default_thickness_mm": 4,
            "typical_cuts": "5",
        },
        "ROMAINE": {
            "name": "羅曼生菜",
            "method": "SEGMENT",
            "default_thickness_mm": 25,
            "typical_cuts": "1",
        },
    }
    
    @staticmethod
    def create(food_type: str, num_cuts: int, thickness_mm: float) -> str:
        """建立切割指令"""
        return f"CHOP,{food_type},{num_cuts},{thickness_mm}"


# ============================================================================
# 4. 放置指令 (PLACE)
# ============================================================================

class PlaceCommand:
    """
    放置指令格式

    CSV: PLACE,<SOURCE>,<LOCATION>,<METHOD>

    SOURCE 是食材目前所在的位置（AS 端先到這裡撈取)，LOCATION 是搬去的目的地。
    SCOOP/PUSH 只送給 F60_F 單獨執行；POUR 需要雙臂在 LOCATION 會合一起傾倒，
    此時 F60_R 只驗證 SOURCE 是否為 MIX_ZONE，不會真的移動過去撈取。

    例子:
        PLACE,WORK_CHOP_ZONE,WAIT_ZONE_1,SCOOP   # 切割區→等待區1(暫放小黃瓜)
        PLACE,WORK_CHOP_ZONE,WAIT_ZONE_2,SCOOP   # 切割區→等待區2(暫放羅曼生菜)
        PLACE,WORK_CHOP_ZONE,MIX_ZONE,SCOOP      # 切割區→混拌區(直接進)
        PLACE,WAIT_ZONE_1,MIX_ZONE,SCOOP         # 等待區1→混拌區(取回小黃瓜)
        PLACE,WAIT_ZONE_2,MIX_ZONE,SCOOP         # 等待區2→混拌區(取回羅曼生菜)
        PLACE,MIX_ZONE,SALAD_BOWL,POUR           # 混拌區→沙拉盤(翻炒完裝盤)
    """

    FORMAT = "PLACE,<SOURCE>,<LOCATION>,<METHOD>"

    VALID_SOURCES = [
        "WORK_CHOP_ZONE",
        "WAIT_ZONE_1",
        "WAIT_ZONE_2",
        "MIX_ZONE",
    ]

    VALID_LOCATIONS = [
        "SALAD_BOWL",
        "WAIT_ZONE_1",
        "WAIT_ZONE_2",
        "MIX_ZONE",
        "WASTE_CORNER",
    ]

    VALID_METHODS = {
        "POUR": "倾倒（主要用于最终沙拉盘）",
        "SCOOP": "用鏟放置（用于中间位置）",
        "PUSH": "推動（用于调整位置）",
    }

    @staticmethod
    def create(source: str, location: str, method: str = "SCOOP") -> str:
        """建立放置指令"""
        return f"PLACE,{source},{location},{method}"


# ============================================================================
# 5. 翻炒指令 (FLIP)
# ============================================================================

class FlipCommand:
    """
    翻炒指令格式
    
    CSV: FLIP,<NUM_CYCLES>,<SPEED_PERCENT>
    
    例子:
        FLIP,6,50              # 翻炒 6 循環，50% 速度
        FLIP,10,60             # 翻炒 10 循環，60% 速度
    """
    
    FORMAT = "FLIP,<NUM_CYCLES>,<SPEED_PERCENT>"
    
    DEFAULTS = {
        "num_cycles": 6,           # 建議 6-10 循環
        "speed_percent": 50,       # 建議 30-60%
        "cycle_height_mm": 100,    # 翻起高度 ≤ 100 mm
    }
    
    @staticmethod
    def create(num_cycles: int, speed_percent: int) -> str:
        """建立翻炒指令"""
        return f"FLIP,{num_cycles},{speed_percent}"


# ============================================================================
# 6. 控制指令 (HOME, STOP, RESET)
# ============================================================================

class HomeCommand:
    """
    回到復歸點指令
    
    CSV: HOME,<ARM>
    
    例子:
        HOME,F60_F             # 左臂回到 HOME_LEFT
        HOME,F60_R             # 右臂回到 HOME_RIGHT
    """
    
    FORMAT = "HOME,<ARM>"
    
    @staticmethod
    def create(arm: str) -> str:
        """建立復歸指令"""
        return f"HOME,{arm}"


class StopCommand:
    """
    緊急停止指令（不需參數）
    
    CSV: STOP
    """
    
    FORMAT = "STOP"
    
    @staticmethod
    def create() -> str:
        """建立停止指令"""
        return "STOP"


class ResetCommand:
    """
    重置指令（清除所有狀態）
    
    CSV: RESET
    """
    
    FORMAT = "RESET"
    
    @staticmethod
    def create() -> str:
        """建立重置指令"""
        return "RESET"


# ============================================================================
# 7. 查詢指令 (STATUS, READY)
# ============================================================================

class StatusCommand:
    """
    查詢機器人狀態
    
    CSV: STATUS,<ARM>
    
    例子:
        STATUS,F60_F
        STATUS,F60_R
    """
    
    FORMAT = "STATUS,<ARM>"
    
    @staticmethod
    def create(arm: str) -> str:
        """建立狀態查詢指令"""
        return f"STATUS,{arm}"


class ReadyCommand:
    """
    查詢機器人是否就緒（可發送下一指令）
    
    CSV: READY,<ARM>
    
    回應: OK (就緒) or BUSY (忙碌中)
    """
    
    FORMAT = "READY,<ARM>"
    
    @staticmethod
    def create(arm: str) -> str:
        """建立就緒狀態查詢指令"""
        return f"READY,{arm}"


# ============================================================================
# 8. 完整菜色指令序列 (Recipes)
# ============================================================================

RECIPES = {
    "菜色1_小黃瓜": {
        "name": "小黃瓜單品",
        "description": "取小黃瓜 → 切 → 放沙拉盤",
        "instructions": [
            "PICKUP,PICKUP_CUCUMBER,F60_F",
            "CHOP,CUCUMBER,5,4",
            "PLACE,WORK_CHOP_ZONE,SALAD_BOWL,POUR",
        ],
    },
    "菜色2_紅蘿蔔": {
        "name": "紅蘿蔔單品",
        "description": "取紅蘿蔔 → 切 → 放沙拉盤",
        "instructions": [
            "PICKUP,PICKUP_CARROT,F60_F",
            "CHOP,CARROT,5,4",
            "PLACE,WORK_CHOP_ZONE,SALAD_BOWL,POUR",
        ],
    },
    "菜色3_羅曼生菜": {
        "name": "羅曼生菜單品",
        "description": "取羅曼生菜 → 切 → 放沙拉盤",
        "instructions": [
            "PICKUP,PICKUP_ROMAINE,F60_F",
            "CHOP,ROMAINE,1,25",
            "PLACE,WORK_CHOP_ZONE,SALAD_BOWL,POUR",
        ],
    },
    "菜色4_生菜沙拉": {
        "name": "生菜沙拉完整流程",
        "description": "完整多菜色組合，必須連續執行",
        "instructions": [
            # 步驟 1: 小黃瓜 → 切 → 暫放等待區1
            "PICKUP,PICKUP_CUCUMBER,F60_F",
            "CHOP,CUCUMBER,5,4",
            "PLACE,WORK_CHOP_ZONE,WAIT_ZONE_1,SCOOP",

            # 步驟 2: 羅曼生菜 → 切 → 暫放等待區2
            "PICKUP,PICKUP_ROMAINE,F60_F",
            "CHOP,ROMAINE,1,25",
            "PLACE,WORK_CHOP_ZONE,WAIT_ZONE_2,SCOOP",

            # 步驟 3: 紅蘿蔔 → 切 → 直接進混拌區
            "PICKUP,PICKUP_CARROT,F60_F",
            "CHOP,CARROT,5,4",
            "PLACE,WORK_CHOP_ZONE,MIX_ZONE,SCOOP",

            # 步驟 4: 取回等待區1(小黃瓜) → 混拌區
            "PLACE,WAIT_ZONE_1,MIX_ZONE,SCOOP",

            # 步驟 5: 取回等待區2(羅曼生菜) → 混拌區
            "PLACE,WAIT_ZONE_2,MIX_ZONE,SCOOP",

            # 步驟 6: 翻炒
            "FLIP,6,50",

            # 步驟 7: 倒沙拉盤
            "PLACE,MIX_ZONE,SALAD_BOWL,POUR",
        ],
    },
}


# ============================================================================
# 9. 指令驗證與解析
# ============================================================================

class CommandParser:
    """指令解析器"""
    
    @staticmethod
    def parse(command_str: str) -> Tuple[str, List[str]]:
        """
        解析 CSV 指令
        
        Args:
            command_str: CSV 字串 (例如 "CHOP,CUCUMBER,5,4")
        
        Returns:
            (命令名, 參數列表) (例如 ("CHOP", ["CUCUMBER", "5", "4"]))
        """
        parts = command_str.strip().split(',')
        cmd_name = parts[0].strip()
        params = [p.strip() for p in parts[1:]]
        return cmd_name, params
    
    @staticmethod
    def validate_pickup(params: List[str]) -> bool:
        """驗證取料指令參數"""
        if len(params) < 5:
            return False
        location, arm = params[0], params[1]
        if not (location in PickupCommand.VALID_LOCATIONS and arm in PickupCommand.VALID_ARMS):
            return False
        try:
            float(params[2])
            float(params[3])
            float(params[4])
        except ValueError:
            return False
        return True
    
    @staticmethod
    def validate_chop(params: List[str]) -> bool:
        """驗證切割指令參數"""
        if len(params) < 3:
            return False
        food_type = params[0]
        try:
            num_cuts = int(params[1])
            thickness = float(params[2])
            return (food_type in ChopCommand.FOOD_TYPES and
                    num_cuts > 0 and thickness > 0)
        except ValueError:
            return False
    
    @staticmethod
    def validate_place(params: List[str]) -> bool:
        """驗證放置指令參數"""
        if len(params) < 3:
            return False
        source, location, method = params[0], params[1], params[2]
        return (source in PlaceCommand.VALID_SOURCES and
                location in PlaceCommand.VALID_LOCATIONS and
                method in PlaceCommand.VALID_METHODS)
    
    @staticmethod
    def validate_flip(params: List[str]) -> bool:
        """驗證翻炒指令參數"""
        if len(params) < 2:
            return False
        try:
            num_cycles = int(params[0])
            speed_percent = int(params[1])
            return (num_cycles > 0 and 1 <= speed_percent <= 100)
        except ValueError:
            return False

    @staticmethod
    def validate_home(params: List[str]) -> bool:
        """驗證復歸指令參數"""
        if len(params) < 1:
            return False
        arm = params[0]
        return arm in PickupCommand.VALID_ARMS


# ============================================================================
# 10. 菜單選擇邏輯（目前未接回主程式，main.py 實際使用 config_phase.MENU）
# ============================================================================

MENU = {
    "1": {
        "name": "菜色 1: 小黃瓜",
        "recipe_key": "菜色1_小黃瓜",
    },
    "2": {
        "name": "菜色 2: 紅蘿蔔",
        "recipe_key": "菜色2_紅蘿蔔",
    },
    "3": {
        "name": "菜色 3: 羅曼生菜",
        "recipe_key": "菜色3_羅曼生菜",
    },
    "4": {
        "name": "菜色 4: 生菜沙拉完整流程",
        "recipe_key": "菜色4_生菜沙拉",
        "continuous": True,  # 必須連續執行
    },
}


# ============================================================================
# 11. 使用範例
# ============================================================================

def get_recipe_instructions(choice: str) -> Optional[List[str]]:
    """
    根據用戶選擇取得指令序列
    
    Args:
        choice: 用戶輸入 ("1", "2", "3", "4")
    
    Returns:
        指令列表，或 None 如果選擇無效
    """
    if choice not in MENU:
        return None
    
    recipe_key = MENU[choice]["recipe_key"]
    return RECIPES[recipe_key]["instructions"]

