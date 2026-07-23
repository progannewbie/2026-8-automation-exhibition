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
    
    CSV: PICKUP,<LOCATION>,<ARM>
    
    例子:
        PICKUP,PICKUP_CUCUMBER,F60_F
        PICKUP,PICKUP_ROMAINE,F60_R
    """
    
    FORMAT = "PICKUP,<LOCATION>,<ARM>"
    
    VALID_LOCATIONS = [
        "PICKUP_CUCUMBER",
        "PICKUP_ROMAINE",
        "PICKUP_RED_LEAF",
    ]
    
    VALID_ARMS = ["F60_F", "F60_R"]  # 通常 F60_F(左臂) 取料
    
    @staticmethod
    def create(location: str, arm: str = "F60_F") -> str:
        """建立取料指令"""
        return f"PICKUP,{location},{arm}"


# ============================================================================
# 3. 切割指令 (CHOP)
# ============================================================================

class ChopCommand:
    """
    切割指令格式
    
    CSV: CHOP,<FOOD_TYPE>,<NUM_CUTS>,<CUT_THICKNESS_MM>
    
    例子:
        CHOP,CUCUMBER,5,4
        CHOP,ROMAINE,8,30
    """
    
    FORMAT = "CHOP,<FOOD_TYPE>,<NUM_CUTS>,<CUT_THICKNESS_MM>"
    
    FOOD_TYPES = {
        "CUCUMBER": {
            "name": "小黃瓜",
            "method": "SLICE",
            "default_thickness_mm": 4,
            "typical_cuts": "5-8",
        },
        "ROMAINE": {
            "name": "蘿蔓生菜",
            "method": "SEGMENT",
            "default_thickness_mm": 30,  # 段長
            "typical_cuts": "6-10",
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
    
    CSV: PLACE,<LOCATION>,<METHOD>
    
    例子:
        PLACE,SALAD_BOWL,POUR        # 倒入沙拉盤
        PLACE,WAIT_ZONE,SCOOP        # 用鏟放到等待區
        PLACE,MIX_ZONE,SCOOP         # 用鏟放到搅拌區
    """
    
    FORMAT = "PLACE,<LOCATION>,<METHOD>"
    
    VALID_LOCATIONS = [
        "SALAD_BOWL",
        "WAIT_ZONE",
        "MIX_ZONE",
        "WASTE_CORNER",
    ]
    
    VALID_METHODS = {
        "POUR": "倾倒（主要用于最终沙拉盘）",
        "SCOOP": "用鏟放置（用于中间位置）",
        "PUSH": "推動（用于调整位置）",
    }
    
    @staticmethod
    def create(location: str, method: str = "SCOOP") -> str:
        """建立放置指令"""
        return f"PLACE,{location},{method}"


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
            "PLACE,SALAD_BOWL,POUR",
        ],
    },
    "菜色2_生菜": {
        "name": "蘿蔓生菜單品",
        "description": "取生菜 → 切 → 放沙拉盤",
        "instructions": [
            "PICKUP,PICKUP_ROMAINE,F60_F",
            "CHOP,ROMAINE,8,30",
            "PLACE,SALAD_BOWL,POUR",
        ],
    },
    "菜色3_紅卷須": {
        "name": "紅卷須生菜單品",
        "description": "取紅卷須 → 放沙拉盤（不切）",
        "instructions": [
            "PICKUP,PICKUP_RED_LEAF,F60_F",
            "PLACE,SALAD_BOWL,POUR",
        ],
    },
    "菜色4_生菜沙拉": {
        "name": "生菜沙拉完整流程",
        "description": "完整多菜色組合，必須連續執行",
        "instructions": [
            # 步驟 1: 小黃瓜 → 等待區
            "PICKUP,PICKUP_CUCUMBER,F60_F",
            "CHOP,CUCUMBER,5,4",
            "PLACE,WAIT_ZONE,SCOOP",
            
            # 步驟 2: 生菜 → 搅拌區
            "PICKUP,PICKUP_ROMAINE,F60_F",
            "CHOP,ROMAINE,8,30",
            "PLACE,MIX_ZONE,SCOOP",
            
            # 步驟 3: 等待區小黃瓜 → 搅拌區
            "PICKUP,WAIT_ZONE,F60_F",
            "PLACE,MIX_ZONE,SCOOP",
            
            # 步驟 4: 紅卷須 → 搅拌區
            "PICKUP,PICKUP_RED_LEAF,F60_F",
            "PLACE,MIX_ZONE,SCOOP",
            
            # 步驟 5: 翻炒
            "FLIP,6,50",
            
            # 步驟 6: 倒沙拉盤
            "PLACE,SALAD_BOWL,POUR",
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
        if len(params) < 2:
            return False
        location, arm = params[0], params[1]
        return (location in PickupCommand.VALID_LOCATIONS and
                arm in PickupCommand.VALID_ARMS)
    
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
        if len(params) < 2:
            return False
        location, method = params[0], params[1]
        return (location in PlaceCommand.VALID_LOCATIONS and
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


# ============================================================================
# 10. 菜單選擇邏輯（main.py 會用到）
# ============================================================================

MENU = {
    "1": {
        "name": "菜色 1: 小黃瓜",
        "recipe_key": "菜色1_小黃瓜",
    },
    "2": {
        "name": "菜色 2: 蘿蔓生菜",
        "recipe_key": "菜色2_生菜",
    },
    "3": {
        "name": "菜色 3: 紅卷須",
        "recipe_key": "菜色3_紅卷須",
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

