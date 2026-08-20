import cv2
import numpy as np
import matplotlib.pyplot as plt


def check_table_with_plate(image_path):
    image = cv2.imread(image_path)

    if image is None:
        raise FileNotFoundError(image_path)

    height, width = image.shape[:2]

    half_h = height // 2
    quarter_w = width // 4

    # =========================
    # 上半部：塗黑右邊兩格
    # =========================
    image[0:half_h, quarter_w * 2:width] = 0

    # =========================
    # 下半部：塗黑最右邊一格
    # =========================
    image[half_h:height, quarter_w * 3:width] = 0

    # =========================
    # Convert to HSV
    # =========================
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    # =========================
    # Vegetable color ranges
    # =========================

    # Green: cucumber / lettuce
    green_lower = np.array([30, 50, 100])
    green_upper = np.array([85, 200, 230])

    # Orange: carrot
    orange_lower = np.array([0, 150, 20])
    orange_upper = np.array([15, 255, 255])

    # =========================
    # Create masks
    # =========================

    green_mask = cv2.inRange(
        hsv,
        green_lower,
        green_upper
    )

    orange_mask = cv2.inRange(
        hsv,
        orange_lower,
        orange_upper
    )

    # Combine
    vegetable_mask = green_mask | orange_mask

    # =========================
    # Remove small noise
    # =========================

    kernel = np.ones((5, 5), np.uint8)

    vegetable_mask = cv2.morphologyEx(
        vegetable_mask,
        cv2.MORPH_OPEN,
        kernel
    )

    vegetable_mask = cv2.morphologyEx(
        vegetable_mask,
        cv2.MORPH_CLOSE,
        kernel
    )

    # =========================
    # Calculate ratio
    # =========================

    vegetable_pixels = cv2.countNonZero(
        vegetable_mask
    )

    total_pixels = vegetable_mask.shape[0] * vegetable_mask.shape[1]

    ratio = vegetable_pixels / total_pixels

    print(f"Vegetable pixel ratio: {ratio:.4%}")

    # =========================
    # Matplotlib visualization
    # =========================

    # OpenCV BGR -> RGB
    #image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    # plt.figure(figsize=(12, 5))

    # # 左：塗黑後圖片
    # plt.subplot(1, 2, 1)
    # plt.imshow(image_rgb)
    # plt.title("Masked Image")
    # plt.axis("off")

    # # 右：Vegetable Mask
    # plt.subplot(1, 2, 2)
    # plt.imshow(vegetable_mask, cmap="gray")
    # plt.title(f"Vegetable Mask\nRatio: {ratio:.4%}")
    # plt.axis("off")

    # plt.tight_layout()
    # plt.show()

    # =========================
    # Threshold
    # =========================

    if ratio > 0.005:
        return False

    return True


# Test
if check_table_with_plate(r"table with plate\capture_009.jpg"):
    print("CLEAN")
else:
    print("NOT CLEAN")