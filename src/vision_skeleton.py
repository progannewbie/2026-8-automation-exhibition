"""
SmartCook 視覺系統 (Vision System)
負責食材檢測、ArUco 標記、Hand-eye calibration
"""

import os
import cv2
import numpy as np
from typing import Dict, List, Tuple, Optional
import logging

from config_vision import (
    YOLOConfig, YOLOOutput, ArUcoConfig, ArUcoOutput,
    HandEyeCalibrationConfig, CoordinateTransform, VisionPrecision,
    VisionProcessingConfig
)

# ============================================================================
# 日誌設定
# ============================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# 1. YOLO 檢測器
# ============================================================================

class YOLODetector:
    """
    YOLOv8 食材檢測器
    
    職責：
    1. 載入 YOLO 模型
    2. 執行推理
    3. 提取中心點和方向角
    """
    
    def __init__(self):
        """初始化 YOLO 檢測器"""
        try:
            from ultralytics import YOLO
        except ImportError:
            logger.error("✗ 未找到 ultralytics 套件，請執行: pip install ultralytics")
            self.model = None
            return

        # 模型尚未訓練/放入前，先留空，不阻擋系統其餘部分運作
        if not os.path.exists(YOLOConfig.MODEL_PATH):
            logger.warning(f"⚠️ YOLO 模型檔案尚未就位: {YOLOConfig.MODEL_PATH}（之後補上即可）")
            self.model = None
            return

        try:
            self.model = YOLO(YOLOConfig.MODEL_PATH)
            logger.info(f"✓ YOLO 模型已載入: {YOLOConfig.MODEL_PATH}")
        except Exception as exc:
            logger.error(f"✗ YOLO 模型載入失敗: {exc}")
            self.model = None
    
    def detect(self, image: np.ndarray) -> List[Dict]:
        """
        執行食材檢測
        
        Args:
            image: 輸入圖像 (H×W×3, BGR 格式)
        
        Returns:
            檢測結果列表，每個元素為:
            {
                'class_id': int,
                'class_name': str,
                'confidence': float,
                'center_x_pixel': float,
                'center_y_pixel': float,
                'width_pixel': float,
                'height_pixel': float,
                'angle_deg': float,
            }
        """
        if self.model is None:
            logger.error("✗ YOLO 模型未初始化")
            return []
        
        try:
            # 執行推理
            results = self.model(
                image,
                conf=YOLOConfig.CONFIDENCE_THRESHOLD,
                iou=YOLOConfig.IOU_THRESHOLD,
                imgsz=YOLOConfig.IMG_SIZE,
                device=YOLOConfig.DEVICE,
                verbose=False
            )
            
            detections = []
            
            # 提取檢測結果
            for result in results:
                boxes = result.boxes
                
                for box in boxes:
                    # 取得邊界框
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    center_x = (x1 + x2) / 2.0
                    center_y = (y1 + y2) / 2.0
                    width = x2 - x1
                    height = y2 - y1
                    
                    # 類別與信心度
                    class_id = int(box.cls[0].cpu().numpy())
                    confidence = float(box.conf[0].cpu().numpy())
                    class_name = YOLOConfig.CLASSES.get(class_id, "UNKNOWN")
                    
                    # 提取方向角（來自 YOLO OBB 輸出或估計）
                    # 簡化版本：假設從邊界框寬高推估
                    if height > width:
                        angle_deg = 90.0  # 豎直
                    else:
                        angle_deg = 0.0   # 水平
                    
                    # 濾除低信心度檢測
                    if confidence < YOLOConfig.CONFIDENCE_THRESHOLD:
                        continue
                    
                    detection = {
                        'class_id': class_id,
                        'class_name': class_name,
                        'confidence': confidence,
                        'center_x_pixel': center_x,
                        'center_y_pixel': center_y,
                        'width_pixel': width,
                        'height_pixel': height,
                        'angle_deg': angle_deg,
                    }
                    
                    detections.append(detection)
            
            logger.info(f"✓ 檢測到 {len(detections)} 個食材")
            return detections
            
        except Exception as e:
            logger.error(f"✗ YOLO 推理失敗: {e}")
            return []


# ============================================================================
# 2. ArUco 檢測器
# ============================================================================

class ArUcoDetector:
    """
    ArUco 標記檢測器
    
    職責：
    1. 載入 ArUco 字典
    2. 檢測標記
    3. 提取標記位置
    """
    
    def __init__(self):
        """初始化 ArUco 檢測器"""
        try:
            self.aruco_dict = cv2.getPredefinedDictionary(
                cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
            )
            self.detector = cv2.aruco.ArucoDetector(self.aruco_dict)
            logger.info("✓ ArUco 檢測器已初始化")
        except Exception as e:
            logger.error(f"✗ ArUco 初始化失敗: {e}")
            self.detector = None
    
    def detect(self, image: np.ndarray) -> List[Dict]:
        """
        檢測 ArUco 標記
        
        Args:
            image: 輸入圖像 (H×W×3 或 H×W)
        
        Returns:
            檢測結果列表，每個元素為:
            {
                'marker_id': int,
                'corners_pixel': [(x1, y1), (x2, y2), (x3, y3), (x4, y4)],
                'center_x_pixel': float,
                'center_y_pixel': float,
            }
        """
        if self.detector is None:
            logger.error("✗ ArUco 檢測器未初始化")
            return []
        
        try:
            # 轉換為灰度圖
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image
            
            # 檢測標記
            corners, ids, rejected = self.detector.detectMarkers(gray)
            
            detections = []
            
            if ids is not None:
                for i, marker_id in enumerate(ids.flatten()):
                    marker_id = int(marker_id)
                    
                    # 取得四個角點
                    corner_points = corners[i][0]  # (4, 2)
                    corners_list = [
                        (float(pt[0]), float(pt[1]))
                        for pt in corner_points
                    ]
                    
                    # 計算中心點
                    center_x = np.mean(corner_points[:, 0])
                    center_y = np.mean(corner_points[:, 1])
                    
                    detection = {
                        'marker_id': marker_id,
                        'corners_pixel': corners_list,
                        'center_x_pixel': float(center_x),
                        'center_y_pixel': float(center_y),
                    }
                    
                    detections.append(detection)
            
            logger.info(f"✓ 檢測到 {len(detections)} 個 ArUco 標記")
            return detections
            
        except Exception as e:
            logger.error(f"✗ ArUco 檢測失敗: {e}")
            return []


# ============================================================================
# 3. Hand-eye Calibrator
# ============================================================================

class HandEyeCalibrator:
    """
    手眼標定器
    
    職責：
    1. 收集標定點對
    2. 計算轉換矩陣
    3. 驗證標定精度
    """
    
    def __init__(self, camera_matrix: Optional[np.ndarray] = None):
        """
        初始化標定器
        
        Args:
            camera_matrix: 相機矩陣 (3×3)
        """
        if camera_matrix is None:
            self.camera_matrix = HandEyeCalibrationConfig.get_default_camera_matrix()
        else:
            self.camera_matrix = camera_matrix
        
        self.pixel_points = []
        self.real_points = []
        self.hand_eye_transform = None
        
        logger.info("✓ Hand-eye Calibrator 已初始化")
    
    def add_calibration_pair(
        self,
        pixel_x: float,
        pixel_y: float,
        real_x_mm: float,
        real_y_mm: float
    ):
        """
        新增標定點對
        
        Args:
            pixel_x: 像素 X 座標
            pixel_y: 像素 Y 座標
            real_x_mm: 現實 X 座標 (mm)
            real_y_mm: 現實 Y 座標 (mm)
        """
        self.pixel_points.append((pixel_x, pixel_y))
        self.real_points.append((real_x_mm, real_y_mm))
        logger.info(f"✓ 新增標定點 ({pixel_x:.1f}, {pixel_y:.1f}) → ({real_x_mm:.1f}, {real_y_mm:.1f})")
    
    def calibrate(self) -> bool:
        """
        執行 Hand-eye 標定
        
        Returns:
            True 標定成功，False 標定失敗
        """
        n_pairs = len(self.pixel_points)
        
        if n_pairs < HandEyeCalibrationConfig.MIN_CALIBRATION_PAIRS:
            logger.error(f"✗ 標定點對不足 ({n_pairs} < {HandEyeCalibrationConfig.MIN_CALIBRATION_PAIRS})")
            return False
        
        try:
            # 計算轉換矩陣
            self.hand_eye_transform = CoordinateTransform.calibrate_hand_eye(
                self.pixel_points,
                self.real_points,
                self.camera_matrix
            )
            
            logger.info("✓ Hand-eye 標定完成")
            logger.info(f"轉換矩陣:\n{self.hand_eye_transform}")
            
            # 驗證精度
            return self._verify_calibration()
            
        except Exception as e:
            logger.error(f"✗ 標定失敗: {e}")
            return False
    
    def _verify_calibration(self) -> bool:
        """
        驗證標定精度
        
        Returns:
            True 精度符合要求，False 精度不足
        """
        if self.hand_eye_transform is None:
            return False
        
        errors = []
        tolerance = HandEyeCalibrationConfig.CALIBRATION_TOLERANCE_MM
        
        for (px, py), (rx, ry) in zip(self.pixel_points, self.real_points):
            # 轉換像素座標
            computed_x, computed_y = CoordinateTransform.pixel_to_real(
                px, py, self.camera_matrix, self.hand_eye_transform
            )
            
            # 計算誤差
            error = np.sqrt((computed_x - rx) ** 2 + (computed_y - ry) ** 2)
            errors.append(error)
        
        mean_error = np.mean(errors)
        max_error = np.max(errors)
        
        logger.info(f"標定精度: 平均誤差 {mean_error:.2f} mm, 最大誤差 {max_error:.2f} mm")
        
        if max_error > tolerance:
            logger.warning(f"⚠️ 最大誤差超過容差 ({max_error:.2f} > {tolerance})")
            return False
        
        return True


# ============================================================================
# 4. 完整視覺系統
# ============================================================================

class VisionSystem:
    """
    整合的視覺系統
    
    職責：
    1. 管理 YOLO、ArUco、Hand-eye calibration
    2. 提供統一的食材檢測 API
    3. 座標轉換
    """
    
    def __init__(self, camera_matrix: Optional[np.ndarray] = None):
        """初始化視覺系統"""
        self.yolo_detector = YOLODetector()
        self.aruco_detector = ArUcoDetector()
        self.calibrator = HandEyeCalibrator(camera_matrix)
        
        logger.info("✓ 視覺系統已初始化")
    
    def detect_foods(self, image: np.ndarray) -> List[Dict]:
        """
        檢測食材並轉換座標
        
        Args:
            image: 輸入圖像
        
        Returns:
            食材檢測結果列表，座標已轉換為現實座標 (mm)
        """
        # 執行 YOLO 檢測
        detections = self.yolo_detector.detect(image)
        
        if not detections or self.calibrator.hand_eye_transform is None:
            logger.warning("⚠️ 無法轉換座標 (標定未完成)")
            return detections
        
        # 轉換座標
        for detection in detections:
            pixel_x = detection['center_x_pixel']
            pixel_y = detection['center_y_pixel']
            
            real_x, real_y = CoordinateTransform.pixel_to_real(
                pixel_x, pixel_y,
                self.calibrator.camera_matrix,
                self.calibrator.hand_eye_transform
            )
            
            # 新增現實座標欄位
            detection['center_x_mm'] = real_x
            detection['center_y_mm'] = real_y
        
        return detections
    
    def detect_aruco_markers(self, image: np.ndarray) -> List[Dict]:
        """
        檢測 ArUco 標記
        
        Args:
            image: 輸入圖像
        
        Returns:
            ArUco 標記檢測結果列表
        """
        return self.aruco_detector.detect(image)
    
    def set_hand_eye_transform(self, transform: np.ndarray):
        """
        設定 Hand-eye 轉換矩陣
        
        Args:
            transform: 4×4 轉換矩陣
        """
        self.calibrator.hand_eye_transform = transform
        logger.info("✓ Hand-eye 轉換矩陣已設定")
    
    def get_location_mm(self, food_name: str, image: np.ndarray) -> Optional[Tuple[float, float]]:
        """
        取得食材在現實世界中的座標
        
        Args:
            food_name: 食材名稱 ("CUCUMBER", "ROMAINE", "RED_LEAF")
            image: 輸入圖像
        
        Returns:
            (x_mm, y_mm) 或 None 如果未檢測到食材
        """
        detections = self.detect_foods(image)
        
        for detection in detections:
            if detection['class_name'] == food_name:
                return (detection['center_x_mm'], detection['center_y_mm'])
        
        logger.warning(f"⚠️ 未檢測到食材: {food_name}")
        return None

