from ultralytics import YOLO
import matplotlib.pyplot as plt
import numpy as np
import cv2
import math

FIELDS = {
    'class_id': int,
    'class_name': str,
    'confidence': float,
    'center_x_pixel': float,
    'center_y_pixel': float,
    'width_pixel': float,
    'height_pixel': float,
    'angle_deg': float,
}

HSV_PARAMS = {
    'cucumber': {
        'lower': np.array([40, 50, 0]),
        'upper': np.array([85, 255, 230]),
    },
    'baby_corn': {
        'lower': np.array([20, 40, 150]),
        'upper': np.array([40, 200, 220]),
    },
    'carrot': {
        'lower': np.array([0, 80, 100]),
        'upper': np.array([20, 255, 230]),
    },
}

CLASS_TO_HSV_KEY = {
    'CUCUMBER': 'cucumber',
    'CORN': 'baby_corn',
    'CARROT': 'carrot',
}

KERNEL = np.ones((5, 5), np.uint8)


def get_mask(img, obj_type):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    params = HSV_PARAMS[obj_type]
    mask = cv2.inRange(hsv, params['lower'], params['upper'])
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, KERNEL)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, KERNEL)
    return mask


def get_rect_axis(contour):
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


def find_head_tail(mask, contour):
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
    print('head/tail area:', area1, area2)

    if area1 < area2:
        head = end1
        tail = end2
    else:
        head = end2
        tail = end1

    return head.astype(int), tail.astype(int), rect


def calculate_angle(head, tail):
    vec = head - tail
    dx = vec[0]
    dy = -vec[1]
    angle = math.degrees(math.atan2(dy, dx))
    if angle < 0:
        angle += 360
    return angle


def select_highest_confidence_obb(obb):
    data = obb.data.cpu().numpy()
    if data.size == 0:
        raise ValueError('No OBB detections found')
    best_idx = int(np.argmax(data[:, 5]))
    return data[best_idx]


def choose_contour_for_box(mask, center_x, center_y, width, height):
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

        M = cv2.moments(contour)
        if M['m00'] != 0:
            cnt_cx = M['m10'] / M['m00']
            cnt_cy = M['m01'] / M['m00']
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


def create_obb_mask(image_shape, center_x, center_y, width, height, angle_deg):
    h, w = image_shape
    obb_mask = np.zeros((h, w), dtype=np.uint8)
    rect = ((center_x, center_y), (width, height), angle_deg)
    box = np.int32(cv2.boxPoints(rect))
    cv2.fillConvexPoly(obb_mask, box, 255)
    return obb_mask


def build_output(img_path):
    model = YOLO('yolo26_smartcook_v2.pt')
    img = cv2.imread(img_path)
    if img is None:
        raise FileNotFoundError(f'Cannot load image: {img_path}')

    results = model.predict(source=img_path, conf=0.3)
    if len(results) == 0:
        raise ValueError('No results returned from YOLO')

    res = results[0]
    obb = res.obb
    if obb is None:
        raise ValueError('No OBB output from model')

    top_data = select_highest_confidence_obb(obb)
    center_x, center_y, width, height, angle_rad, confidence, class_id = top_data
    class_id = int(class_id)
    class_name = model.names[class_id]
    obj_type = CLASS_TO_HSV_KEY.get(class_name.upper())
    if obj_type is None:
        raise ValueError(f'Unsupported class name: {class_name}')

    mask = get_mask(img, obj_type)
    obb_angle_deg = math.degrees(angle_rad)
    obb_mask = create_obb_mask(img.shape[:2], center_x, center_y, width, height, obb_angle_deg)
    mask = cv2.bitwise_and(mask, obb_mask)

    contour = choose_contour_for_box(mask, center_x, center_y, width, height)
    if contour is None:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if len(contours) == 0:
            raise ValueError(f'No {obj_type} contour found inside OBB mask')
        contour = max(contours, key=cv2.contourArea)

    head, tail, rect = find_head_tail(mask, contour)
    angle_deg = calculate_angle(head, tail)
    obb_angle_deg = math.degrees(angle_rad)

    fields = {
        'class_id': class_id,
        'class_name': class_name,
        'confidence': float(confidence),
        'center_x_pixel': float(center_x),
        'center_y_pixel': float(center_y),
        'width_pixel': float(width),
        'height_pixel': float(height),
        'angle_deg': float(angle_deg),
    }

    return fields, img, mask, contour, head, tail, rect, obb_angle_deg


if __name__ == '__main__':
    image_path = r'images\\new_capture_216.jpg'
    fields, img, mask, contour, head, tail, rect, obb_angle_deg = build_output(image_path)
    print('FIELDS =', fields)

    result = img.copy()
    rect_points = np.int32(cv2.boxPoints(((fields['center_x_pixel'], fields['center_y_pixel']), (fields['width_pixel'], fields['height_pixel']), obb_angle_deg)))
    cv2.drawContours(result, [rect_points], 0, (0, 0, 255), 2)
    cv2.arrowedLine(result, tuple(tail), tuple(head), (0, 255, 255), 4)
    cv2.putText(result, f"{fields['class_name']} {fields['angle_deg']:.1f} deg", (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)

    result_rgb = cv2.cvtColor(result, cv2.COLOR_BGR2RGB)
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))
    axes[0].imshow(mask, cmap='gray')
    axes[0].set_title(f"{fields['class_name']} mask")
    axes[0].axis('off')

    axes[1].imshow(result_rgb)
    axes[1].set_title(f"{fields['class_name']} direction: {fields['angle_deg']:.1f}°")
    axes[1].axis('off')
    plt.tight_layout()
    plt.show()