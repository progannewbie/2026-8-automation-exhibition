"""
SmartCook 視覺配置 (Vision Configuration)
YOLO 模型、ArUco 標記、Hand-eye calibration 相關參數
"""

from enum import Enum
from typing import Dict, Tuple, List, Optional
import numpy as np

# ============================================================================
# 1. YOLO 相關配置
# ============================================================================

class YOLOConfig:
    """YOLOv8 模型配置"""
    
    # 模型參數
    MODEL_PATH = "models/yolov8_smartcook_v1.pt"  # 待訓練模型路徑
    CONFIDENCE_THRESHOLD = 0.7  # 信心閾值
    IOU_THRESHOLD = 0.5  # IoU 非極大值抑制閾值
    
    # 類別定義
    CLASSES = {
        0: "CUCUMBER",      # 小黃瓜
        1: "ROMAINE",       # 蘿蔓生菜
        2: "RED_LEAF",      # 紅卷須生菜
    }
    
    CLASS_NAMES = {v: k for k, v in CLASSES.items()}  # 反向映射
    
    # 推理參數
    IMG_SIZE = 640                 # 輸入圖像尺寸
    BATCH_SIZE = 1                 # 批次大小
    DEVICE = "cpu"                 # "cpu" 或 "cuda"
    HALF_PRECISION = False         # 是否使用 FP16


class YOLOOutput:
    """YOLO 輸出格式"""
    
    FIELDS = {
        'class_id': int,           # 類別 ID (0/1/2)
        'class_name': str,         # 類別名稱
        'confidence': float,       # 信心度 (0.0-1.0)
        'center_x_pixel': float,   # 中心點像素 X
        'center_y_pixel': float,   # 中心點像素 Y
        'width_pixel': float,      # 邊界框寬度（像素）
        'height_pixel': float,     # 邊界框高度（像素）
        'angle_deg': float,        # 食材長軸方向角 (0-360°)
    }
    
    @staticmethod
    def example() -> Dict:
        """
        YOLO 輸出範例
        
        Returns:
            檢測結果字典
        """
        return {
            'class_id': 0,
            'class_name': 'CUCUMBER',
            'confidence': 0.92,
            'center_x_pixel': 320.5,
            'center_y_pixel': 240.3,
            'width_pixel': 80.0,
            'height_pixel': 150.0,
            'angle_deg': 45.0,
        }


# ============================================================================
# 2. ArUco 標記配置
# ============================================================================

class ArUcoConfig:
    """ArUco 標記配置"""
    
    DICTIONARY = "DICT_5X5_100"    # ArUco 字典
    MARKER_SIZE_MM = 50             # 標記實際邊長 (mm)
    
    # 標記定義
    MARKERS = {
        101: {
            'name': 'WORK_ZONE_REF',
            'description': '工作區基準標記',
            'real_coordinate_mm': None,  # 待現場測量
        },
        102: {
            'name': 'SALAD_BOWL_REF',
            'description': '沙拉盤基準標記',
            'real_coordinate_mm': None,  # 待現場測量
        },
    }
    
    # 檢測參數
    DETECTION_PARAMS = {
        'min_marker_perimeter': 50,  # 最小標記周長
        'adaptive_thresh_constant': 7,
    }


class ArUcoOutput:
    """ArUco 輸出格式"""
    
    FIELDS = {
        'marker_id': int,           # 標記 ID
        'corners_pixel': List[Tuple[float, float]],  # 四個角點 [(x1,y1), ...]
        'center_x_pixel': float,    # 中心點像素 X
        'center_y_pixel': float,    # 中心點像素 Y
    }
    
    @staticmethod
    def example() -> Dict:
        """
        ArUco 檢測結果範例
        
        Returns:
            檢測結果字典
        """
        return {
            'marker_id': 102,
            'corners_pixel': [
                (400.0, 300.0),   # 左上
                (500.0, 300.0),   # 右上
                (500.0, 400.0),   # 右下
                (400.0, 400.0),   # 左下
            ],
            'center_x_pixel': 450.0,
            'center_y_pixel': 350.0,
        }


# ============================================================================
# 3. Hand-eye Calibration 配置
# ============================================================================

class HandEyeCalibrationConfig:
    """手眼標定配置"""
    
    # 標定精度要求
    CALIBRATION_TOLERANCE_MM = 3.0  # 標定精度 ±3mm
    
    # 相機內參（待標定填充）
    CAMERA_MATRIX = None            # 3×3 相機矩陣 K
    DIST_COEFFS = None              # 畸變係數
    
    # Hand-eye 轉換矩陣（待標定填充）
    HAND_EYE_TRANSFORM = None       # 4×4 齊次轉換矩陣
    
    # 標定點對數量
    MIN_CALIBRATION_PAIRS = 5       # 最少 5 對點進行標定
    
    @staticmethod
    def get_default_camera_matrix() -> np.ndarray:
        """
        預設相機矩陣（估計值）
        
        實際使用前必須通過標定獲得準確值
        """
        # 假設 640×480 圖像，焦距約 500 像素
        return np.array([
            [500, 0, 320],     # fx, 0, cx
            [0, 500, 240],     # 0, fy, cy
            [0, 0, 1]          # 0, 0, 1
        ], dtype=np.float32)


class CoordinateTransform:
    """座標轉換工具"""
    
    @staticmethod
    def pixel_to_real(
        pixel_x: float,
        pixel_y: float,
        camera_matrix: np.ndarray,
        hand_eye_transform: np.ndarray,
        z_mm: float = 0.0
    ) -> Tuple[float, float]:
        """
        將像素座標轉換為現實座標
        
        Args:
            pixel_x: 像素 X 座標
            pixel_y: 像素 Y 座標
            camera_matrix: 相機矩陣 K (3×3)
            hand_eye_transform: Hand-eye 轉換矩陣 (4×4)
            z_mm: 食材所在檯面 Z 座標（通常為 0）
        
        Returns:
            (real_x_mm, real_y_mm) — 現實座標
        """
        # 逆相機矩陣
        K_inv = np.linalg.inv(camera_matrix)
        
        # 標準化座標
        pixel_homogeneous = np.array([pixel_x, pixel_y, 1.0])
        normalized = K_inv @ pixel_homogeneous
        
        # 齊次座標 (2D 標準化 → 3D 齊次)
        camera_point = np.array([normalized[0], normalized[1], 0.0, 1.0])
        
        # 應用 hand-eye 轉換
        world_point = hand_eye_transform @ camera_point
        
        # 回傳現實座標 (mm)
        return float(world_point[0]), float(world_point[1])
    
    @staticmethod
    def calibrate_hand_eye(
        pixel_points: List[Tuple[float, float]],
        real_points: List[Tuple[float, float]],
        camera_matrix: np.ndarray
    ) -> np.ndarray:
        """
        從標定點對計算 Hand-eye 轉換矩陣
        
        Args:
            pixel_points: 像素座標列表 [(u1, v1), (u2, v2), ...]
            real_points: 現實座標列表 [(x1, y1), (x2, y2), ...] (mm)
            camera_matrix: 相機矩陣 K (3×3)
        
        Returns:
            Hand-eye 轉換矩陣 (4×4)
        
        Note:
            需要至少 5 對標定點以獲得穩定的轉換矩陣
        """
        # 這裡是簡化的實現，實際應使用更穩健的標定演算法
        # 例如 Tsai-Lenz hand-eye calibration
        
        n_points = len(pixel_points)
        
        # 構建線性系統
        A = []
        b = []
        
        K_inv = np.linalg.inv(camera_matrix)
        
        for (px, py), (rx, ry) in zip(pixel_points, real_points):
            # 標準化座標
            pixel_homogeneous = np.array([px, py, 1.0])
            normalized = K_inv @ pixel_homogeneous
            
            # 構建方程
            A.append([normalized[0], normalized[1], 1, 0, 0, 0])
            A.append([0, 0, 0, normalized[0], normalized[1], 1])
            
            b.append(rx)
            b.append(ry)
        
        A = np.array(A)
        b = np.array(b)
        
        # 最小二乘求解
        x, residuals, rank, s = np.linalg.lstsq(A, b, rcond=None)
        
        # 構建 4×4 轉換矩陣
        transform = np.eye(4)
        transform[0, 0:3] = [x[0], x[1], x[2]]  # 第一行 (x 轉換)
        transform[1, 0:3] = [x[3], x[4], x[5]]  # 第二行 (y 轉換)
        transform[2, 2] = 1.0                    # Z 保持不變
        
        return transform


# ============================================================================
# 4. 視覺檢測精度與公差
# ============================================================================

class VisionPrecision:
    """視覺檢測精度定義"""
    
    YOLO_DETECTION_PRECISION = {
        'center_position_mm': 5.0,      # 中心點位置精度 ±5mm
        'angle_precision_deg': 5.0,     # 方向角精度 ±5°
    }
    
    ARUCO_DETECTION_PRECISION = {
        'center_position_mm': 3.0,      # 中心點位置精度 ±3mm
    }
    
    HAND_EYE_CALIBRATION_PRECISION = {
        'position_mm': 3.0,             # 座標轉換精度 ±3mm
    }


# ============================================================================
# 5. 視覺處理流程參數
# ============================================================================

class VisionProcessingConfig:
    """視覺處理流程配置"""
    
    # 相機參數
    CAMERA_RESOLUTION = (640, 480)    # (寬, 高)
    CAMERA_FPS = 30                   # 影格率
    
    # 圖像處理
    UNDISTORT_IMAGES = True           # 是否進行畸變矯正
    CLAHE_ENABLED = True              # 自適應直方圖均衡
    CLAHE_CLIP_LIMIT = 2.0
    
    # 輸出
    DEBUG_DRAW_BBOX = True            # 繪製檢測框
    DEBUG_DRAW_CENTERS = True         # 繪製中心點
    DEBUG_DRAW_ANGLES = True          # 繪製方向角
    
    # 檔案儲存
    SAVE_CALIBRATION_DATA = True
    CALIBRATION_DATA_PATH = "data/calibration/hand_eye_calibration.npy"
    YOLO_MODEL_PATH = "models/yolov8_smartcook_v1.pt"


# ============================================================================
# 6. 使用範例
# ============================================================================

def get_yolo_classes() -> Dict[int, str]:
    """取得 YOLO 類別映射"""
    return YOLOConfig.CLASSES.copy()


def get_aruco_markers() -> Dict[int, Dict]:
    """取得 ArUco 標記定義"""
    return ArUcoConfig.MARKERS.copy()

