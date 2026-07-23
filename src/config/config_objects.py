"""
SmartCook 物件定義配置 (Object Definitions Configuration)
食材、工具、位置點的標準字串與結構定義
座標系：檯面左下角 (0, 0)，單位 mm
"""

from enum import Enum
from typing import Dict, Tuple, Optional

# ============================================================================
# 1. 食材定義 (FoodType)
# ============================================================================

class FoodType(Enum):
    """食材類型列舉"""
    CUCUMBER = "CUCUMBER"          # 小黃瓜
    ROMAINE = "ROMAINE"            # 蘿蔓生菜
    RED_LEAF = "RED_LEAF"          # 紅捲鬚生菜


FOOD_METADATA = {
    FoodType.CUCUMBER: {
        'name': '小黃瓜',
        'description': '細長圓柱型，約 20cm 長',
        'color': 'green',
        'typical_weight_g': 200,
        'cut_thickness_mm': 4,  # 建議切片厚度
        'cut_method': 'SLICE',  # 切片方式
    },
    FoodType.ROMAINE: {
        'name': '蘿蔓生菜',
        'description': '葉菜，長條型',
        'color': 'green',
        'typical_weight_g': 300,
        'cut_length_mm': 30,  # 建議段長
        'cut_method': 'SEGMENT',  # 分段方式
    },
    FoodType.RED_LEAF: {
        'name': '紅捲鬚生菜',
        'description': '結球蔬菜，鬚狀葉',
        'color': 'red_purple',
        'typical_weight_g': 400,
        'cut_method': 'GATHER',  # 聚攏方式（不切，直接聚）
    },
}

# ============================================================================
# 2. 工具定義 (ToolType)
# ============================================================================

class ToolType(Enum):
    """工具類型列舉"""
    LEFT_SPATULA = "LEFT_SPATULA"    # 左鏟（開刃，切割用）
    RIGHT_SPATULA = "RIGHT_SPATULA"  # 右鏟（不開刃，壓菜/聚攏用）


TOOL_METADATA = {
    ToolType.LEFT_SPATULA: {
        'name': '左鏟',
        'arm': 'F60_F',  # 對應左臂
        'description': '開刃鐵鏟，用於食材切割',
        'blade_edge': True,  # 有刀刃
        'blade_angle_deg': 45,  # 研磨角度 (估計)
        'primary_function': 'CHOP',
        'functions': ['CHOP', 'CUT'],
    },
    ToolType.RIGHT_SPATULA: {
        'name': '右鏟',
        'arm': 'F60_R',  # 對應右臂
        'description': '平面鐵鏟，用於壓菜、聚攏、托運',
        'blade_edge': False,  # 無刀刃
        'primary_function': 'HOLD',
        'functions': ['HOLD', 'PUSH', 'GATHER', 'SCOOP'],
    },
}

# ============================================================================
# 3. 位置點定義 (LocationPoint)
# ============================================================================

class LocationPoint(Enum):
    """檯面上的標準位置點"""
    
    # --- 取料區 (Pickup Zone) ---
    PICKUP_CUCUMBER = "PICKUP_CUCUMBER"          # 小黃瓜取料點
    PICKUP_ROMAINE = "PICKUP_ROMAINE"            # 蘿蔓取料點
    PICKUP_RED_LEAF = "PICKUP_RED_LEAF"          # 紅捲鬚取料點
    
    # --- 工作區 (Work Zone) ---
    WORK_CHOP_ZONE = "WORK_CHOP_ZONE"            # 切割區（食材準備區）
    WORK_MIX_ZONE = "WORK_MIX_ZONE"              # 混拌區（切好食材聚集點）
    WORK_FLIP_ZONE = "WORK_FLIP_ZONE"            # 翻炒區（翻炒動作中心）
    
    # --- 放置區 (Placement Zone) ---
    SALAD_BOWL = "SALAD_BOWL"                    # 沙拉盤位置（最終放置）
    WASTE_CORNER = "WASTE_CORNER"                # 廢料角（根部段放置）
    
    # --- 機器人待機 (Home Position) ---
    HOME_LEFT = "HOME_LEFT"                      # 左臂復歸點
    HOME_RIGHT = "HOME_RIGHT"                    # 右臂復歸點


LOCATION_METADATA = {
    # 取料區
    LocationPoint.PICKUP_CUCUMBER: {
        'name': '小黃瓜取料點',
        'zone': 'PICKUP',
        'description': '放置小黃瓜的位置，鏟子從上方接近',
        'food_type': FoodType.CUCUMBER,
        'approach_from': 'TOP',  # 接近方向
        'coordinate_mm': None,  # 待視覺系統 + 手工標定
        'angle_deg': None,      # 食材長軸方向角
    },
    LocationPoint.PICKUP_ROMAINE: {
        'name': '蘿蔓取料點',
        'zone': 'PICKUP',
        'description': '放置蘿蔓的位置，鏟子從上方接近',
        'food_type': FoodType.ROMAINE,
        'approach_from': 'TOP',
        'coordinate_mm': None,
        'angle_deg': None,
    },
    LocationPoint.PICKUP_RED_LEAF: {
        'name': '紅捲鬚取料點',
        'zone': 'PICKUP',
        'description': '放置紅捲鬚的位置，鏟子從側方接近',
        'food_type': FoodType.RED_LEAF,
        'approach_from': 'SIDE',
        'coordinate_mm': None,
        'angle_deg': None,
    },
    
    # 工作區
    LocationPoint.WORK_CHOP_ZONE: {
        'name': '切割區',
        'zone': 'WORK',
        'description': '進行切割動作的區域，通常在檯面中央',
        'width_mm': 400,  # 區域寬度（估計）
        'length_mm': 300,  # 區域長度（估計）
        'center_coordinate_mm': None,  # 區域中心座標，待標定
    },
    LocationPoint.WORK_MIX_ZONE: {
        'name': '混拌區',
        'zone': 'WORK',
        'description': '三種食材聚集、混合的區域',
        'center_coordinate_mm': None,
    },
    LocationPoint.WORK_FLIP_ZONE: {
        'name': '翻炒區',
        'zone': 'WORK',
        'description': '進行翻炒動作的中心點，鏟子在此互補翻動',
        'center_coordinate_mm': None,
    },
    
    # 放置區
    LocationPoint.SALAD_BOWL: {
        'name': '沙拉盤',
        'zone': 'PLACEMENT',
        'description': '最終盛放沙拉的盤子位置，鏟子在此傾倒食材',
        'approach_from': 'TOP',
        'coordinate_mm': None,  # 盤子中心座標
        'orientation': 'FIXED',  # 固定不動
    },
    LocationPoint.WASTE_CORNER: {
        'name': '廢料角',
        'zone': 'PLACEMENT',
        'description': '放置蘿蔓根部等廢料的區域',
        'coordinate_mm': None,
    },
    
    # 機器人待機
    LocationPoint.HOME_LEFT: {
        'name': '左臂復歸點',
        'zone': 'HOME',
        'description': '左臂未使用時的待機位置，高度安全',
        'arm': 'F60_F',
        'coordinate_mm': None,  # 待手工標定
        'angle_deg': None,
    },
    LocationPoint.HOME_RIGHT: {
        'name': '右臂復歸點',
        'zone': 'HOME',
        'description': '右臂未使用時的待機位置，高度安全',
        'arm': 'F60_R',
        'coordinate_mm': None,
        'angle_deg': None,
    },
}

# ============================================================================
# 4. 座標與姿態定義
# ============================================================================

class CoordinateFormat:
    """
    座標與姿態格式定義
    
    坐標系：
    - 原點：檯面左下角 (0, 0)
    - X 軸：向右
    - Y 軸：向前（朝向觀眾）
    - Z 軸：向上
    - 單位：毫米 (mm)
    
    姿態 (Orientation)：
    - 角度：食材或工具的長軸與 X 軸的夾角
    - 範圍：0° ~ 360°
    - 0°：平行於 X 軸（朝右）
    - 90°：平行於 Y 軸（朝前）
    """
    
    @staticmethod
    def create_point_2d(x_mm: float, y_mm: float) -> Tuple[float, float]:
        """建立 2D 座標點 (X, Y)"""
        return (x_mm, y_mm)
    
    @staticmethod
    def create_point_3d(x_mm: float, y_mm: float, z_mm: float) -> Tuple[float, float, float]:
        """建立 3D 座標點 (X, Y, Z)"""
        return (x_mm, y_mm, z_mm)
    
    @staticmethod
    def create_pose_2d(x_mm: float, y_mm: float, angle_deg: float) -> Dict:
        """建立 2D 姿態 (X, Y, 角度)"""
        return {
            'x': x_mm,
            'y': y_mm,
            'angle_deg': angle_deg % 360,  # 正規化角度
        }


# ============================================================================
# 5. 取料區間距定義
# ============================================================================

PICKUP_ZONE_CONSTRAINTS = {
    'min_distance_between_foods_mm': 80,  # 三種食材之間最小距離
    'ideal_spacing_mm': 150,  # 理想間距
    'checkerboard_layout': True,  # 棋盤式擺放（推薦）
}

# ============================================================================
# 6. 視覺檢測相關常數
# ============================================================================

VISION_DETECTION = {
    # YOLO 類別對應
    'yolo_classes': {
        0: FoodType.CUCUMBER,
        1: FoodType.ROMAINE,
        2: FoodType.RED_LEAF,
    },
    
    # ArUco 標記點
    'aruco_markers': {
        'WORK_ZONE_REF': 101,      # 工作區基準標記
        'SALAD_BOWL_REF': 102,     # 沙拉盤基準標記
    },
    
    # 檢測精度要求
    'detection_confidence_threshold': 0.7,  # YOLO 信心閾值
    'hand_eye_calibration_tolerance_mm': 3,  # hand-eye 精度容差
}

# ============================================================================
# 7. 統一查詢函式
# ============================================================================

def get_location_coordinates(loc: LocationPoint) -> Optional[Tuple[float, float]]:
    """
    查詢位置點的座標
    
    Args:
        loc: LocationPoint 列舉值
    
    Returns:
        (x, y) 座標 (mm)，或 None 如果尚未標定
    """
    return LOCATION_METADATA[loc].get('coordinate_mm')


def get_location_angle(loc: LocationPoint) -> Optional[float]:
    """
    查詢位置點的方向角
    
    Args:
        loc: LocationPoint 列舉值
    
    Returns:
        角度 (度)，或 None 如果尚未標定
    """
    return LOCATION_METADATA[loc].get('angle_deg')


def get_food_name(food: FoodType) -> str:
    """取得食材的中文名稱"""
    return FOOD_METADATA[food]['name']


def get_tool_name(tool: ToolType) -> str:
    """取得工具的中文名稱"""
    return TOOL_METADATA[tool]['name']


def get_food_by_pickup_location(loc: LocationPoint) -> Optional[FoodType]:
    """從取料位置反查食材類型"""
    metadata = LOCATION_METADATA.get(loc)
    if metadata and 'food_type' in metadata:
        return metadata['food_type']
    return None

