"""
SmartCook 純影像處理定位 (HSV Color-Based Head/Tail Detection)

搬自 automation-2026-yolo-main 專案（imgProcessing.py / imgProcessing_whole_folder.py /
test_full_result.py 三支腳本共用的核心演算法），拿掉各自的 matplotlib 展示/CLI 程式碼，
整理成可以直接被 vision_skeleton.py 匯入使用的函式。

兩種用法：
1. 不跑 YOLO，純色彩分割：detect_by_color()。速度比跑 YOLO 快很多，但沒有分類信心度，
   且畫面中只能有一種預期食材（會挑遮罩面積最大的顏色，其餘食材會被忽略）。
2. 搭配 YOLO 使用（對應 test_full_result.py 的做法）：YOLO 先框出食材位置與類別，
   refine_angle_with_yolo_box() 用該類別對應的色彩範圍在框內做遮罩交集，避免抓到
   畫面裡其他同色物體，再算出完整 0–360° 角度，取代 YOLO OBB 本身只有 0–180° 週期
   的角度輸出（見 vision_skeleton.py 的 YOLODetector.detect() 說明）。

★ HSV_PARAMS 目前只有 cucumber/baby_corn/carrot 三組色域，是換菜前「玉米筍」的配色，
   還沒有羅曼生菜（葉菜）的色彩範圍，也還沒現場重新測試調整。
"""

import math
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

# =========================
# HSV 色域參數
# =========================
HSV_PARAMS = {
    "cucumber": {
        "lower": np.array([40, 50, 0]),
        "upper": np.array([85, 255, 230]),
    },
    "baby_corn": {
        "lower": np.array([20, 30, 150]),
        "upper": np.array([40, 200, 220]),
    },
    "carrot": {
        "lower": np.array([0, 80, 100]),
        "upper": np.array([20, 255, 230]),
    },
}

# YOLO 類別名稱 → HSV_PARAMS 的 key（搭配 YOLO 使用時查表用）
CLASS_TO_HSV_KEY = {
    "CUCUMBER": "cucumber",
    "CORN": "baby_corn",
    "CARROT": "carrot",
}

KERNEL = np.ones((5, 5), np.uint8)


def get_mask(img: np.ndarray, obj_type: str) -> np.ndarray:
    """依 HSV_PARAMS[obj_type] 的色域門檻，回傳二值遮罩（含開運算/閉運算去雜訊）"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    params = HSV_PARAMS[obj_type]
    mask = cv2.inRange(hsv, params["lower"], params["upper"])
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, KERNEL)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, KERNEL)
    return mask


def detect_object_type(img: np.ndarray) -> Tuple[str, np.ndarray]:
    """
    不用 YOLO，純色彩分割：HSV_PARAMS 三種色域都跑一次，挑遮罩面積最大的當結果。
    畫面中只能有一種預期食材，否則會被面積最大的顏色蓋過去。
    """
    best_type = None
    best_area = 0
    best_mask = None

    for obj_type in HSV_PARAMS:
        mask = get_mask(img, obj_type)
        area = int(np.count_nonzero(mask))
        if area > best_area:
            best_area = area
            best_type = obj_type
            best_mask = mask

    if best_area <= 1000:
        raise ValueError("No cucumber, baby corn, or carrot found")

    return best_type, best_mask


def get_rect_axis(contour: np.ndarray):
    """用 minAreaRect 取得最小外接矩形與長軸方向向量"""
    rect = cv2.minAreaRect(contour)
    center, size, angle = rect
    w, h = size
    if w >= h:
        angle_deg = angle
    else:
        angle_deg = angle + 90
    angle_rad = math.radians(angle_deg)
    axis = np.array([math.cos(angle_rad), math.sin(angle_rad)])
    return rect, axis, max(w, h)


def find_head_tail(mask: np.ndarray, contour: np.ndarray):
    """
    沿長軸把輪廓投影到兩端，再比較「前 20%」與「後 20%」範圍內的遮罩面積，
    面積較小的一端視為「頭」（較尖/較細的一端），藉此判斷食材的頭尾方向。
    """
    rect, axis, length = get_rect_axis(contour)
    center = np.array(rect[0])
    points = contour.reshape(-1, 2)
    projection = (points - center) @ axis
    min_p = np.min(projection)
    max_p = np.max(projection)
    end1 = center + axis * min_p
    end2 = center + axis * max_p

    h, w = mask.shape
    yy, xx = np.indices((h, w))
    pixels = np.stack([xx - center[0], yy - center[1]], axis=-1)
    proj = pixels @ axis
    range_len = max_p - min_p
    if range_len == 0:
        range_len = 1
    front_limit = min_p + range_len * 0.2
    back_limit = max_p - range_len * 0.2
    region1 = (proj <= front_limit) & (proj >= min_p) & (mask > 0)
    region2 = (proj >= back_limit) & (proj <= max_p) & (mask > 0)
    area1 = np.sum(region1)
    area2 = np.sum(region2)

    if area1 < area2:
        head, tail = end1, end2
    else:
        head, tail = end2, end1

    return head.astype(int), tail.astype(int), rect


def calculate_angle(head: np.ndarray, tail: np.ndarray) -> float:
    """依頭尾向量算出完整 0–360° 方向角（YOLO OBB 本身只有 0–180° 週期）"""
    vec = head - tail
    dx = vec[0]
    dy = -vec[1]
    angle = math.degrees(math.atan2(dy, dx))
    if angle < 0:
        angle += 360
    return angle


def detect_by_color(img: np.ndarray) -> Dict:
    """
    不用 YOLO，純色彩分割 + 頭尾判斷，直接回傳跟 YOLODetector.detect() 相容的欄位。
    速度比跑 YOLO 快很多，但沒有分類信心度、畫面只能有一種預期食材。
    """
    obj_type, mask = detect_object_type(img)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if len(contours) == 0:
        raise ValueError(f"No {obj_type} contour found")

    contour = max(contours, key=cv2.contourArea)
    head, tail, rect = find_head_tail(mask, contour)
    angle_deg = calculate_angle(head, tail)
    center_x, center_y = rect[0]
    width, height = rect[1]

    return {
        "class_name": obj_type,
        "confidence": None,  # 純色彩分割沒有信心度
        "center_x_pixel": float(center_x),
        "center_y_pixel": float(center_y),
        "width_pixel": float(width),
        "height_pixel": float(height),
        "angle_deg": angle_deg,
        "angle_source": "color_head_tail",  # 0-360°，跟 YOLODetector 的 'obb'/'estimated' 不同
    }


def choose_contour_for_box(
    mask: np.ndarray, center_x: float, center_y: float, width: float, height: float
) -> Optional[np.ndarray]:
    """
    在遮罩裡可能有多個輪廓時，挑跟 YOLO OBB 框重疊面積大、輪廓面積大、
    且輪廓中心離框中心近的那一個（三項加權評分），避免抓到框外的雜訊輪廓。
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    best_contour = None
    best_score = -1.0
    half_w = width / 2.0
    half_h = height / 2.0

    for contour in contours:
        area = cv2.contourArea(contour)
        if area <= 0:
            continue

        x, y, w, h = cv2.boundingRect(contour)
        overlap_w = max(0.0, min(x + w, center_x + half_w) - max(x, center_x - half_w))
        overlap_h = max(0.0, min(y + h, center_y + half_h) - max(y, center_y - half_h))
        overlap = overlap_w * overlap_h

        m = cv2.moments(contour)
        if m["m00"] != 0:
            cnt_cx = m["m10"] / m["m00"]
            cnt_cy = m["m01"] / m["m00"]
        else:
            cnt_cx = x + w / 2.0
            cnt_cy = y + h / 2.0

        dist = np.hypot(cnt_cx - center_x, cnt_cy - center_y)
        score = overlap * 2.0 + area * 0.01 - dist * 0.05

        if score > best_score:
            best_score = score
            best_contour = contour

    if best_contour is None:
        best_contour = max(contours, key=cv2.contourArea)

    return best_contour


def create_obb_mask(
    image_shape: Tuple[int, int], center_x: float, center_y: float,
    width: float, height: float, angle_deg: float,
) -> np.ndarray:
    """把 YOLO 的 OBB(中心/寬高/角度)畫成一張二值遮罩，用來跟色彩遮罩做交集"""
    h, w = image_shape
    obb_mask = np.zeros((h, w), dtype=np.uint8)
    rect = ((center_x, center_y), (width, height), angle_deg)
    box = np.int32(cv2.boxPoints(rect))
    cv2.fillConvexPoly(obb_mask, box, 255)
    return obb_mask


def refine_angle_with_yolo_box(
    img: np.ndarray,
    class_name: str,
    center_x: float,
    center_y: float,
    width: float,
    height: float,
    obb_angle_deg: float,
) -> Optional[float]:
    """
    搭配 YOLO 使用（對應 test_full_result.py 的 build_output()）：
    用 YOLO 框出的類別與 OBB 範圍，把色彩遮罩限制在框內，取得完整 0–360° 角度，
    取代 YOLO OBB 本身只有 0–180° 週期的角度。偵測不到就回傳 None，呼叫端應
    fallback 回 YOLO 原本的 angle_deg。
    """
    obj_type = CLASS_TO_HSV_KEY.get(class_name.upper())
    if obj_type is None:
        return None

    mask = get_mask(img, obj_type)
    obb_mask = create_obb_mask(img.shape[:2], center_x, center_y, width, height, obb_angle_deg)
    mask = cv2.bitwise_and(mask, obb_mask)

    contour = choose_contour_for_box(mask, center_x, center_y, width, height)
    if contour is None:
        return None

    head, tail, _ = find_head_tail(mask, contour)
    return calculate_angle(head, tail)
