"""
SmartCook 視覺系統 (Vision System)
負責食材檢測、ArUco 標記、Hand-eye calibration
"""

import math
import os
import cv2
import numpy as np
from typing import Dict, List, Tuple, Optional
import logging

from config_vision import (
    YOLOConfig, YOLOOutput, ArUcoConfig, ArUcoOutput,
    HandEyeCalibrationConfig, CoordinateTransform, VisionPrecision,
    VisionProcessingConfig, TableHomography, ChopZoneHomography
)
import img_processing

# ============================================================================
# 日誌設定
# ============================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def long_axis_endpoints_px(d: Dict) -> Tuple[Tuple[float, float], Tuple[float, float], float]:
    """
    偵測框長軸的兩個端點（像素）與長軸長度

    OBB 的 angle_deg 是寬邊 (width) 的方向；高比寬長時長軸要轉 90°。
    非 OBB 模型 (angle_source='estimated') 的框是軸對齊的，angle 只有 0/90 的粗估。
    色彩精算過的 angle (color_head_tail) 是頭尾方向，本身就沿長軸。
    """
    w, h = d['width_pixel'], d['height_pixel']
    length = max(w, h)
    if d['angle_source'] == 'color_head_tail':
        theta = math.radians(d['angle_deg'])
    elif d['angle_source'] == 'obb':
        theta = math.radians(d['angle_deg'] + (90.0 if h > w else 0.0))
    else:  # estimated：軸對齊框
        theta = math.radians(90.0 if h > w else 0.0)
    dx, dy = math.cos(theta) * length / 2, math.sin(theta) * length / 2
    cx, cy = d['center_x_pixel'], d['center_y_pixel']
    return (cx - dx, cy - dy), (cx + dx, cy + dy), length


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
                'angle_deg': float,       # 度數範圍依 angle_source 而定
                'angle_source': str,      # 'obb'：模型直接輸出的旋轉角，0-180°週期
                                           # 'estimated'：非 OBB 模型，用長短邊粗略猜 0/90°
                                           # 'color_head_tail'：img_processing 用色彩
                                           # 分割在框內判斷頭尾，完整 0-360°，見下方精算段
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
                # OBB (Oriented Bounding Box) 模型會有 result.obb，直接附旋轉角，
                # 精準度遠比用長寬猜的好，優先使用；一般 (軸對齊) 模型才 fallback 到 boxes。
                # 注意：OBB 模型即使這張畫面 0 個偵測，result.obb 也不是 None（只是空的），
                # 但 result.boxes 在 OBB 模型上本來就是 None——用 obb is not None 判斷任務
                # 類型即可，不能再用 len(obb) > 0，不然 0 偵測那幀會誤判成一般模型，
                # 掉進下面的 for box in boxes 對 None 做 iterate 而炸掉。
                obb = getattr(result, 'obb', None)

                if obb is not None:
                    for i in range(len(obb)):
                        center_x, center_y, width, height, rot_rad = (
                            obb.xywhr[i].cpu().numpy().tolist()
                        )
                        class_id = int(obb.cls[i].cpu().numpy())
                        confidence = float(obb.conf[i].cpu().numpy())

                        if confidence < YOLOConfig.CONFIDENCE_THRESHOLD:
                            continue

                        class_name = YOLOConfig.CLASSES.get(class_id, "UNKNOWN")
                        angle_deg = math.degrees(rot_rad) % 180.0

                        detections.append({
                            'class_id': class_id,
                            'class_name': class_name,
                            'confidence': confidence,
                            'center_x_pixel': center_x,
                            'center_y_pixel': center_y,
                            'width_pixel': width,
                            'height_pixel': height,
                            'angle_deg': angle_deg,
                            'angle_source': 'obb',
                        })
                    continue  # 這個 result 已經用 OBB 取完，不再重複用 boxes 算一次

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

                    # 濾除低信心度檢測
                    if confidence < YOLOConfig.CONFIDENCE_THRESHOLD:
                        continue

                    # 非 OBB 模型沒有真正的旋轉角，只能用長短邊粗略猜 0°/90°，
                    # 準確度有限，僅供參考 (angle_source 標成 'estimated')
                    angle_deg = 90.0 if height > width else 0.0

                    detection = {
                        'class_id': class_id,
                        'class_name': class_name,
                        'confidence': confidence,
                        'center_x_pixel': center_x,
                        'center_y_pixel': center_y,
                        'width_pixel': width,
                        'height_pixel': height,
                        'angle_deg': angle_deg,
                        'angle_source': 'estimated',
                    }

                    detections.append(detection)

            # 用色彩分割在 YOLO 框內做頭尾判斷，取得完整 0–360° 角度，取代 'obb'/
            # 'estimated' 只有 0–180° 週期的角度；偵測不到（例如 LETTUCE 刻意沒有
            # HSV 色域，見 img_processing.py）就保留原本角度，不影響既有流程。
            for detection in detections:
                # 精算會把 angle_deg 換成「頭→尾」方向，但框本身的幾何（寬邊方向）
                # 還是要用原本的角度，量長軸端點時才不會把框轉錯 90°
                detection['box_angle_deg'] = detection['angle_deg']
                try:
                    refined_angle = img_processing.refine_angle_with_yolo_box(
                        image,
                        detection['class_name'],
                        detection['center_x_pixel'],
                        detection['center_y_pixel'],
                        detection['width_pixel'],
                        detection['height_pixel'],
                        detection['angle_deg'],
                    )
                except Exception as exc:
                    logger.warning(f"⚠️ 色彩頭尾角度精算失敗，維持原本角度: {exc}")
                    refined_angle = None

                if refined_angle is not None:
                    detection['angle_deg'] = refined_angle
                    detection['angle_source'] = 'color_head_tail'

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
            self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
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
    1. 管理 YOLO、ArUco、座標標定
    2. 提供統一的食材檢測 API
    3. 座標轉換

    座標轉換預設走 TableHomography（檯面單應性，2026-08-13 現場 9 點標定，
    RMS 2.13mm）。食材都躺在同一個平面上，像素平面到檯面之間就是一個 3×3
    單應性矩陣，不需要相機內參。只有在呼叫過 set_hand_eye_transform() 之後
    才會改走 4×4 hand-eye 那條路。
    """

    def __init__(self, camera_matrix: Optional[np.ndarray] = None):
        """初始化視覺系統"""
        self.yolo_detector = YOLODetector()
        self.aruco_detector = ArUcoDetector()
        self.calibrator = HandEyeCalibrator(camera_matrix)

        logger.info("✓ 視覺系統已初始化")
        logger.info(f"  座標轉換: 檯面單應性 (RMS {TableHomography.RMS_ERROR_MM}mm, "
                    f"最大 {TableHomography.MAX_ERROR_MM}mm)")

    def detect_foods(self, image: np.ndarray) -> List[Dict]:
        """
        檢測食材並轉換座標

        Args:
            image: 輸入圖像

        Returns:
            食材檢測結果列表，每筆都會有 center_x_mm / center_y_mm，
            以及 coord_source 標示座標是用哪條路算的
        """
        detections = self.yolo_detector.detect(image)
        if not detections:
            return detections

        # 有設定 hand-eye 才走那條；預設用檯面單應性
        use_hand_eye = self.calibrator.hand_eye_transform is not None

        for detection in detections:
            pixel_x = detection['center_x_pixel']
            pixel_y = detection['center_y_pixel']

            if use_hand_eye:
                real_x, real_y = CoordinateTransform.pixel_to_real(
                    pixel_x, pixel_y,
                    self.calibrator.camera_matrix,
                    self.calibrator.hand_eye_transform
                )
                detection['coord_source'] = 'hand_eye'
                detection['in_calibrated_area'] = True
            else:
                real_x, real_y = TableHomography.pixel_to_mm(pixel_x, pixel_y)
                detection['coord_source'] = 'table_homography'

                # 標定範圍外是外推，透視項會讓誤差快速放大。
                # get_location_mm / get_location_and_angle_mm 會把這種偵測當成沒找到。
                in_area = TableHomography.is_within_calibrated_area(pixel_x, pixel_y)
                detection['in_calibrated_area'] = in_area
                if not in_area:
                    logger.warning(
                        f"⚠️ {detection['class_name']} 在 ({pixel_x:.0f},{pixel_y:.0f})，"
                        f"超出標定範圍 u{TableHomography.U_RANGE} v{TableHomography.V_RANGE}，"
                        f"座標 ({real_x:.1f},{real_y:.1f})mm 是外推值，誤差可能遠大於 "
                        f"{TableHomography.MAX_ERROR_MM}mm"
                    )

            detection['center_x_mm'] = real_x
            detection['center_y_mm'] = real_y

        return detections
    
    def capture_frame(self) -> Optional[np.ndarray]:
        """
        從相機拍攝一張畫面（取料前視覺確認用）

        Returns:
            BGR 影像，或 None 如果相機無法使用（失敗時不拋出例外，交由呼叫端決定如何處理）
        """
        try:
            cap = cv2.VideoCapture(VisionProcessingConfig.CAMERA_INDEX)
            if not cap.isOpened():
                logger.warning(f"⚠️ 無法開啟相機 index={VisionProcessingConfig.CAMERA_INDEX}")
                return None

            width, height = VisionProcessingConfig.CAMERA_RESOLUTION
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

            # 丟棄暖機畫面，避免用到自動曝光/白平衡還沒穩定的第一張
            for _ in range(VisionProcessingConfig.CAMERA_WARMUP_FRAMES):
                cap.read()

            ok, frame = cap.read()
            cap.release()

            if not ok:
                logger.warning("⚠️ 相機已開啟，但讀取畫面失敗")
                return None

            return frame

        except Exception as exc:
            logger.warning(f"⚠️ 相機拍照異常: {exc}")
            return None

    def verify_food_present(self, food_type: str) -> bool:
        """
        取料前的視覺確認：拍照後用 YOLO 檢查指定食材是否存在

        只做「有沒有偵測到」的確認，不影響送給機器人的指令內容（CSV 通訊格式不變）。
        YOLO 模型未載入或相機無法使用時，視為確認能力暫時不可用，回傳 True 讓流程照常進行，
        避免視覺子系統本身的問題連帶擋住整條取料流程。

        Args:
            food_type: 期望偵測到的食材類別（例如 "CUCUMBER"、"CARROT"、"LETTUCE"）

        Returns:
            True：偵測到該食材，或確認能力目前不可用；False：確實沒偵測到
        """
        if self.yolo_detector.model is None:
            logger.warning(f"⚠️ YOLO 模型未載入，略過取料前確認: {food_type}")
            return True

        image = self.capture_frame()
        if image is None:
            logger.warning(f"⚠️ 無法取得相機畫面，略過取料前確認: {food_type}")
            return True

        detections = self.yolo_detector.detect(image)
        found = any(d['class_name'] == food_type for d in detections)

        if found:
            logger.info(f"✓ 視覺確認: 偵測到 {food_type}")
        else:
            logger.warning(f"⚠️ 視覺確認: 未偵測到 {food_type}")

        return found

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
        設定 Hand-eye 轉換矩陣，並改由它接手座標轉換

        ⚠️ 設定之後 detect_foods() 就不再走 TableHomography。hand-eye 需要
           準確的相機內參才會準，而 config_vision.get_default_camera_matrix()
           目前還是估計值（640×480、焦距 500）。除非內參已經標定過，否則
           不要呼叫這支——預設的檯面單應性反而準得多。

        Args:
            transform: 4×4 轉換矩陣
        """
        self.calibrator.hand_eye_transform = transform
        logger.warning("⚠️ 已切換為 Hand-eye 轉換，不再使用檯面單應性")
    
    def _find_usable(self, food_name: str, image: np.ndarray) -> Optional[Dict]:
        """
        找第一個類別相符、而且座標可信的偵測結果

        ⚠️ 落在標定範圍外的偵測一律不用：單應性在範圍外是外推，誤差會遠大於
           MAX_ERROR_MM，把那種座標送給手臂可能夾空或撞到東西。寧可回 None
           讓呼叫端重拍／中止，也不要送一個不可信的點。
           取料區如果真的在範圍外，該做的是重新標定把它涵蓋進去，
           不是放寬這裡（見 config_vision.TableHomography）。
        """
        detections = self.detect_foods(image)
        matches = [d for d in detections if d['class_name'] == food_name]

        for detection in matches:
            if detection.get('in_calibrated_area', True):
                return detection

        if matches:
            d = matches[0]
            logger.warning(
                f"⚠️ {food_name} 在 ({d['center_x_pixel']:.0f},{d['center_y_pixel']:.0f})，"
                f"超出標定範圍，不使用這個座標"
            )
        else:
            logger.warning(f"⚠️ 未檢測到食材: {food_name}")
        return None

    def get_location_mm(self, food_name: str, image: np.ndarray) -> Optional[Tuple[float, float]]:
        """
        取得食材在現實世界中的座標
        
        Args:
            food_name: YOLO 類別名稱 ("CUCUMBER", "CARROT", "LETTUCE")
            image: 輸入圖像

        Returns:
            (x_mm, y_mm) 或 None 如果未檢測到食材、或食材在標定範圍外
        """
        detection = self._find_usable(food_name, image)
        if detection is None:
            return None
        return (detection['center_x_mm'], detection['center_y_mm'])

    def get_location_and_angle_mm(
        self, food_name: str, image: np.ndarray
    ) -> Optional[Tuple[float, float, float]]:
        """
        取得食材在現實世界中的座標與旋轉角，給 PICKUP 指令即時定位用

        角度直接沿用 YOLODetector 輸出的 angle_deg。CUCUMBER/CARROT 已用
        img_processing 的色彩頭尾判斷精算成完整 0-360°（angle_source ==
        'color_head_tail'）；LETTUCE 不需分頭尾、刻意沒有 HSV 色域，會用 OBB 的
        0-180° 週期角度（或非 OBB 模型的長寬估計值），見 YOLODetector.detect()。

        Args:
            food_name: YOLO 類別名稱 ("CUCUMBER", "CARROT", "LETTUCE")
            image: 輸入圖像

        Returns:
            (x_mm, y_mm, angle_deg) 或 None 如果未檢測到食材、或食材在標定範圍外
        """
        detection = self._find_usable(food_name, image)
        if detection is None:
            return None
        return (
            detection['center_x_mm'],
            detection['center_y_mm'],
            detection['angle_deg'],
        )

    def measure_on_table(
        self, food_name: str, image: np.ndarray
    ) -> Tuple[Optional[Dict], str]:
        """
        用取料區座標（TableHomography）量食材兩端，給切割區還沒標定時的偏移估算用
        （config_phase.TableOffsetEstimate）

        切割區通常在取料區標定範圍外，座標是外推值——位置不能直接拿來下刀，
        只靠現場對點資料換算成偏移；長度只用到比例尺，相對可靠。
        畫面上有多個同類偵測時用信心度最高的（畫面邊緣常有別根或誤判）。

        Returns:
            (結果, 說明)。結果為 None 表示量不到；否則
            {
                'ends_mm': [(x, y), (x, y)],   # 取料區座標，不分頭尾
                'right_end_mm': (x, y),        # X 較大那端（第一刀那端）
                'length_mm': float,
                'axis_angle_deg': float,       # 長軸跟取料區 X 軸的夾角，0～90°
                'confidence': float,
            }
        """
        detections = [d for d in self.yolo_detector.detect(image) if d['class_name'] == food_name]
        if not detections:
            return None, f"畫面裡找不到 {food_name}"
        d = max(detections, key=lambda x: x['confidence'] or 0.0)

        p1, p2, _ = long_axis_endpoints_px(d)
        m1, m2 = TableHomography.pixel_to_mm(*p1), TableHomography.pixel_to_mm(*p2)
        dx, dy = m2[0] - m1[0], m2[1] - m1[1]
        angle = abs(math.degrees(math.atan2(dy, dx))) % 180.0
        result = {
            'ends_mm': [m1, m2],
            'right_end_mm': max(m1, m2, key=lambda p: p[0]),
            'length_mm': float(math.hypot(dx, dy)),
            'axis_angle_deg': min(angle, 180.0 - angle),
            'confidence': d['confidence'],
        }
        logger.info(
            f"✓ 取料區座標量測 {food_name}: 兩端 ({m1[0]:.1f},{m1[1]:.1f}) / ({m2[0]:.1f},{m2[1]:.1f}) mm，"
            f"長 {result['length_mm']:.1f}mm，偏角 {result['axis_angle_deg']:.1f}°，"
            f"信心度 {d['confidence']:.2f}（共 {len(detections)} 個偵測）"
        )
        return result, ""

    def measure_in_chop_zone(
        self, food_name: str, image: np.ndarray
    ) -> Tuple[Optional[Dict], str]:
        """
        量切割區裡食材的兩端位置（左臂基座座標），給「從頂點起切」決定下刀起點

        只看落在切割區標定範圍內的偵測——取料區可能還放著別根同類食材，
        不能拿來量。座標走 ChopZoneHomography，不是取料用的 TableHomography。

        Args:
            food_name: YOLO 類別名稱（例如 "CUCUMBER"）
            image: 切割區畫面

        Returns:
            (結果, 說明)。結果為 None 表示量不到，說明寫原因；否則結果是
            {
                'ends_mm': [(x, y), (x, y)],   # 長軸兩端，左臂基座座標，不分頭尾
                'length_mm': float,
                'axis_angle_deg': float,      # 長軸跟左臂 X 軸的夾角，0～90°
                'source': 'color' | 'obb',    # 端點來自色彩輪廓或 YOLO 框
                'center_pixel': (u, v),
            }
        """
        if not ChopZoneHomography.is_calibrated():
            return None, "切割區尚未標定"

        detections = self.yolo_detector.detect(image)
        in_zone = [
            d for d in detections
            if d['class_name'] == food_name and
            ChopZoneHomography.is_within_calibrated_area(d['center_x_pixel'], d['center_y_pixel'])
        ]
        if not in_zone:
            return None, f"切割區裡找不到 {food_name}"
        if len(in_zone) > 1:
            logger.warning(f"⚠️ 切割區裡有 {len(in_zone)} 個 {food_name}，用信心度最高的那個")
        d = max(in_zone, key=lambda x: x['confidence'] or 0.0)

        ends = img_processing.measure_axis_endpoints(
            image, d['class_name'],
            d['center_x_pixel'], d['center_y_pixel'],
            d['width_pixel'], d['height_pixel'],
            d.get('box_angle_deg', d['angle_deg']) % 180.0,   # 框的寬邊方向，不是精算後的頭尾方向
        )
        if ends is None:
            return None, f"{food_name} 的框大小異常，量不到兩端"

        ends_mm = [ChopZoneHomography.pixel_to_mm(*ends['end1']),
                   ChopZoneHomography.pixel_to_mm(*ends['end2'])]
        dx = ends_mm[1][0] - ends_mm[0][0]
        dy = ends_mm[1][1] - ends_mm[0][1]
        angle = abs(math.degrees(math.atan2(dy, dx))) % 180.0
        angle = min(angle, 180.0 - angle)

        result = {
            'ends_mm': ends_mm,
            'length_mm': float(math.hypot(dx, dy)),
            'axis_angle_deg': angle,
            'source': ends['source'],
            'center_pixel': (d['center_x_pixel'], d['center_y_pixel']),
        }
        logger.info(
            f"✓ 切割區量測 {food_name}: 兩端 ({ends_mm[0][0]:.1f},{ends_mm[0][1]:.1f}) / "
            f"({ends_mm[1][0]:.1f},{ends_mm[1][1]:.1f}) mm，長 {result['length_mm']:.1f}mm，"
            f"偏角 {angle:.1f}°（端點來源: {ends['source']}）"
        )
        return result, "ok"

