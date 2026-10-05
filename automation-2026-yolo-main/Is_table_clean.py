import cv2
import numpy as np

def check_table(image_path):
    image = cv2.imread(image_path)
    if image is None:
        raise FileNotFoundError(image_path)
    # Convert to HSV
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    # -----------------------------
    # Vegetable color ranges
    # -----------------------------
    # Green: cucumber / lettuce

    green_lower = np.array([30, 50, 100])
    green_upper = np.array([85, 200, 230])

    # Orange: carrot
    orange_lower = np.array([0, 150, 20])
    orange_upper = np.array([15, 255, 255])
    # Create masks
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
    vegetable_mask = (
        green_mask |
        orange_mask
    )
    # Remove small noise
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
    # Calculate percentage of vegetable-colored pixels
    vegetable_pixels = cv2.countNonZero(
        vegetable_mask
    )
    total_pixels = vegetable_mask.shape[0] * vegetable_mask.shape[1]
    ratio = vegetable_pixels / total_pixels
    print(f"Vegetable pixel ratio: {ratio:.4%}")
    # Threshold
    if ratio > 0.1:
        return False
    return True
# Test

if check_table(r"table images\image copy 3.png"):
    print("CLEAN")
else:
    print("NOT CLEAN")