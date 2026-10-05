import cv2
import numpy as np
import math
import os
import matplotlib.pyplot as plt

IMAGE_PATH = r"images\new_capture_004.jpg"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}

HSV_PARAMS = {
    "cucumber": {
        "lower": np.array([40, 50, 0]),
        "upper": np.array([85, 255, 230])
    },
    "baby_corn": {
        "lower": np.array([20, 30, 150]),
        "upper": np.array([40, 200, 220])
    },
    "carrot": {
        "lower": np.array([0, 80, 100]),
        "upper": np.array([20, 255, 230])
    }
}

KERNEL = np.ones((5, 5), np.uint8)

# =========================
# HSV segmentation
# =========================
def get_mask(img, obj_type):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    params = HSV_PARAMS[obj_type]
    mask = cv2.inRange(hsv, params["lower"], params["upper"])
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, KERNEL)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, KERNEL)
    return mask


def detect_object_type(img):
    best_type = None
    best_area = 0
    best_mask = None

    for obj_type in HSV_PARAMS:
        mask = get_mask(img, obj_type)
        area = int(np.count_nonzero(mask))
        print(f"{obj_type}: mask area = {area}")
        if area > best_area:
            best_area = area
            best_type = obj_type
            best_mask = mask

    if best_area <= 1000:
        raise Exception("No cucumber, baby corn, or carrot found")

    return best_type, best_mask


# =========================
# minAreaRect取得長軸
# =========================
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


# =========================
# 沿長軸找頭尾
# =========================
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
    front_limit = min_p + range_len * 0.2
    back_limit = max_p - range_len * 0.2
    region1 = (proj <= front_limit) & (proj >= min_p) & (mask > 0)
    region2 = (proj >= back_limit) & (proj <= max_p) & (mask > 0)
    area1 = np.sum(region1)
    area2 = np.sum(region2)
    print("head/tail area:", area1, area2)

    if area1 < area2:
        head = end1
        tail = end2
    else:
        head = end2
        tail = end1

    return head.astype(int), tail.astype(int), rect


# =========================
# 計算360角度
# =========================
def calculate_angle(head, tail):
    vec = head - tail
    dx = vec[0]
    dy = -vec[1]
    angle = math.degrees(math.atan2(dy, dx))
    if angle < 0:
        angle += 360
    return angle


def list_image_files(folder):
    files = [f for f in os.listdir(folder) if os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS]
    files.sort()
    return [os.path.join(folder, f) for f in files]


def process_image(path):
    print(f"Processing: {path}")
    img = cv2.imread(path)
    if img is None:
        raise Exception(f"Cannot load image: {path}")

    obj_type, mask = detect_object_type(img)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if len(contours) == 0:
        raise Exception(f"No {obj_type} contour found in {path}")

    contour = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(contour)
    print("area:", area)

    head, tail, rect = find_head_tail(mask, contour)
    angle = calculate_angle(head, tail)
    print("Direction:", round(angle, 2), "degree")

    result = img.copy()
    box = cv2.boxPoints(rect)
    box = np.int32(box)
    cv2.drawContours(result, [box], 0, (0, 0, 255), 2)
    cv2.arrowedLine(result, tuple(tail), tuple(head), (0, 255, 255), 4)
    cv2.putText(result, f"{obj_type} {angle:.1f} deg", (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)

    result_rgb = cv2.cvtColor(result, cv2.COLOR_BGR2RGB)
    return mask, result_rgb, obj_type, angle, area


# =========================
# Main
# =========================

if not os.path.exists(IMAGE_PATH):
    raise Exception(f"Image not found: {IMAGE_PATH}")

folder = os.path.dirname(IMAGE_PATH) or "."
image_files = list_image_files(folder)
if not image_files:
    raise Exception(f"No images found in folder: {folder}")

if IMAGE_PATH in image_files:
    current_index = image_files.index(IMAGE_PATH)
else:
    current_index = 0

fig, axes = plt.subplots(1, 2, figsize=(12, 6))
fig.suptitle("Use left/right arrow keys to navigate images")

mask_img = None
result_img = None


def update_display(index):
    global mask_img, result_img
    path = image_files[index]
    mask, result_rgb, obj_type, angle, area = process_image(path)

    if mask_img is None:
        mask_img = axes[0].imshow(mask, cmap="gray", vmin=0, vmax=255)
        result_img = axes[1].imshow(result_rgb)
    else:
        mask_img.set_data(mask)
        result_img.set_data(result_rgb)

    axes[0].set_title(f"{os.path.basename(path)} - {obj_type} mask")
    axes[1].set_title(f"{os.path.basename(path)} - {obj_type} direction: {angle:.1f}°")
    axes[0].axis("off")
    axes[1].axis("off")
    fig.canvas.draw_idle()


def on_key(event):
    global current_index
    if event.key == "right":
        current_index = (current_index + 1) % len(image_files)
        update_display(current_index)
    elif event.key == "left":
        current_index = (current_index - 1) % len(image_files)
        update_display(current_index)

fig.canvas.mpl_connect("key_press_event", on_key)
update_display(current_index)
plt.tight_layout()
plt.show()