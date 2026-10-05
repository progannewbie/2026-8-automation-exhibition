# Vision API 快速參考

## 初始化

```python
from vision_skeleton import VisionSystem
import cv2

vision = VisionSystem()
```

## 檢測食材（返回現實座標）

```python
image = cv2.imread("scene.jpg")
detections = vision.detect_foods(image)

for det in detections:
    print(f"{det['class_name']}: ({det['center_x_mm']:.1f}, {det['center_y_mm']:.1f}) mm")
```

## 快速查詢單個食材

```python
location = vision.get_location_mm("CUCUMBER", image)
if location:
    x, y = location
    print(f"座標: ({x:.1f}, {y:.1f}) mm")
```

## Hand-eye 標定

```python
# 新增標定點（5 對以上）
vision.calibrator.add_calibration_pair(100, 150, 50, 75)
vision.calibrator.add_calibration_pair(200, 250, 100, 125)
# ... 新增更多

# 執行標定
success = vision.calibrator.calibrate()
```

## ArUco 標記檢測

```python
markers = vision.detect_aruco_markers(image)

for marker in markers:
    print(f"標記 {marker['marker_id']}: ({marker['center_x_pixel']:.1f}, {marker['center_y_pixel']:.1f})")
```

## 輸出格式

### YOLO 檢測結果

```python
{
    'class_id': 0,                    # 0=CUCUMBER, 1=CARROT, 2=CORN
    'class_name': 'CUCUMBER',
    'confidence': 0.92,
    'center_x_pixel': 320.5,          # 像素座標
    'center_y_pixel': 240.3,
    'center_x_mm': 150.0,             # 現實座標（標定後）
    'center_y_mm': 120.0,
    'width_pixel': 80.0,
    'height_pixel': 150.0,
    'angle_deg': 45.0,
}
```

### ArUco 檢測結果

```python
{
    'marker_id': 102,
    'corners_pixel': [(400, 300), (500, 300), (500, 400), (400, 400)],
    'center_x_pixel': 450.0,
    'center_y_pixel': 350.0,
}
```

## 精度要求

| 項目 | 要求 |
|------|------|
| YOLO 位置精度 | ±5 mm |
| YOLO 角度精度 | ±5° |
| Hand-eye 標定精度 | ±3 mm |
| 信心度閾值 | ≥ 0.7 |

## 常用方法

| 方法 | 說明 |
|------|------|
| `vision.detect_foods(image)` | 檢測所有食材（返回現實座標） |
| `vision.get_location_mm(food_name, image)` | 查詢單個食材座標 |
| `vision.get_location_and_angle_mm(food_name, image)` | 查詢單個食材座標＋旋轉角（PICKUP 用） |
| `vision.detect_aruco_markers(image)` | 檢測 ArUco 標記 |
| `vision.calibrator.add_calibration_pair(px, py, rx, ry)` | 新增標定點 |
| `vision.calibrator.calibrate()` | 執行 Hand-eye 標定 |
| `vision.set_hand_eye_transform(transform)` | 設定標定結果 |

## 食材類別

| class_id | 英文 | 中文 |
|----------|------|------|
| 0 | CUCUMBER | 小黃瓜 |
| 1 | CARROT | 紅蘿蔔 |
| 2 | CORN | 玉米筍 |

## ArUco 標記 ID

| ID | 名稱 | 用途 |
|----|------|------|
| 101 | WORK_ZONE_REF | 工作區基準 |
| 102 | SALAD_BOWL_REF | 沙拉盤基準 |
