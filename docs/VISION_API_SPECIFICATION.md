# SmartCook 視覺 API 規範 (Vision API Specification)

**版本**: v1.0  
**日期**: 2026/7/23  
**作者**: Wilson (視覺) + Zhang (軟體)  
**狀態**: ✅ 定案

---

## 📋 目錄

1. [系統架構](#系統架構)
2. [YOLO 檢測 API](#yolo-檢測-api)
3. [ArUco 標記 API](#aruco-標記-api)
4. [Hand-eye Calibration](#hand-eye-calibration)
5. [座標轉換](#座標轉換)
6. [使用範例](#使用範例)

---

## 系統架構

### 四層架構

```
Layer 1: 原始輸入
  ↓
  └─→ 相機圖像 (640×480, BGR)

Layer 2: 檢測
  ↓
  └─→ YOLODetector (食材檢測)
  └─→ ArUcoDetector (基準標記)

Layer 3: 座標轉換
  ↓
  └─→ HandEyeCalibrator (像素 → 現實座標)

Layer 4: API 輸出
  ↓
  └─→ VisionSystem.detect_foods() — 食材座標 (mm)
  └─→ VisionSystem.get_location_mm(food_name)
```

### 座標系統

```
相機視角（俯視）:

     (0,0) 左上角 (640,0) 右上角
        +────────────────→ X (像素)
        |
        | 相機俯拍
        | 檯面檢測區域
        ↓ Y (像素)
     (0,480)          (640,480)

現實座標系（根據 Hand-eye 標定）:

        Y (朝向觀眾)
        ↑
        |
        +──────→ X (向右)
        |
        O (0,0) 檯面左下角
```

---

## YOLO 檢測 API

### YOLODetector.detect()

**目的**: 檢測圖像中的所有食材

**簽名**:
```python
def detect(image: np.ndarray) -> List[Dict]
```

**輸入參數**:

| 參數 | 類型 | 說明 |
|------|------|------|
| image | np.ndarray | 輸入圖像 (H×W×3, BGR 格式) |

**輸出**:

每個檢測結果為字典：

```python
{
    'class_id': int,           # 類別 ID: 0=CUCUMBER, 1=CARROT, 2=CORN
    'class_name': str,         # 類別名稱: "CUCUMBER" 等
    'confidence': float,       # 信心度 (0.0-1.0)，閾值 ≥ 0.7
    'center_x_pixel': float,   # 中心點 X (像素座標)
    'center_y_pixel': float,   # 中心點 Y (像素座標)
    'width_pixel': float,      # 邊界框寬度 (像素)
    'height_pixel': float,     # 邊界框高度 (像素)
    'angle_deg': float,        # 食材長軸方向角 (0-360°)
}
```

**精度要求**:

| 項目 | 要求 |
|------|------|
| 位置精度 | ±5 mm |
| 角度精度 | ±5° |
| 信心度閾值 | ≥ 0.7 |

**使用範例**:

```python
from vision_skeleton import VisionSystem
import cv2

vision = VisionSystem()
image = cv2.imread("food_image.jpg")
detections = vision.yolo_detector.detect(image)

for det in detections:
    print(f"{det['class_name']}: ({det['center_x_pixel']:.1f}, {det['center_y_pixel']:.1f}), "
          f"confidence={det['confidence']:.2f}")
```

**回應範例**:

```
CUCUMBER: (320.5, 240.3), confidence=0.92
CARROT: (150.2, 180.4), confidence=0.88
```

---

## ArUco 標記 API

### ArUcoDetector.detect()

**目的**: 檢測圖像中的 ArUco 基準標記

**簽名**:
```python
def detect(image: np.ndarray) -> List[Dict]
```

**輸出**:

每個標記檢測結果為字典：

```python
{
    'marker_id': int,                    # 標記 ID: 101, 102
    'corners_pixel': [                   # 四個角點 (逆時針)
        (x1_pixel, y1_pixel),           # 左上
        (x2_pixel, y2_pixel),           # 右上
        (x3_pixel, y3_pixel),           # 右下
        (x4_pixel, y4_pixel),           # 左下
    ],
    'center_x_pixel': float,            # 中心點 X
    'center_y_pixel': float,            # 中心點 Y
}
```

**有效標記 ID**:

| ID | 名稱 | 用途 |
|----|----|------|
| 101 | WORK_ZONE_REF | 工作區基準標記 |
| 102 | SALAD_BOWL_REF | 沙拉盤基準標記 |

**使用範例**:

```python
markers = vision.aruco_detector.detect(image)

for marker in markers:
    print(f"標記 {marker['marker_id']}: 中心 ({marker['center_x_pixel']:.1f}, {marker['center_y_pixel']:.1f})")
```

---

## Hand-eye Calibration

### 標定流程

#### 步驟 1: 收集標定點對

```python
calibrator = vision.calibrator

# 使用標尺測量檯面上的 5+ 個點
# 紀錄: (像素 X, 像素 Y) → (現實 X mm, 現實 Y mm)

calibrator.add_calibration_pair(
    pixel_x=100.0,
    pixel_y=150.0,
    real_x_mm=50.0,
    real_y_mm=75.0
)

calibrator.add_calibration_pair(
    pixel_x=500.0,
    pixel_y=300.0,
    real_x_mm=250.0,
    real_y_mm=150.0
)

# ... 新增至少 5 對點
```

#### 步驟 2: 執行標定

```python
success = calibrator.calibrate()

if success:
    print("✓ 標定成功")
    print(f"平均誤差: {calibrator._verify_calibration()}")
else:
    print("✗ 標定失敗，請檢查點對數量和精度")
```

#### 步驟 3: 驗證精度

```python
# 標定後自動驗證，要求:
# - 最大誤差 ≤ 3 mm
# - 平均誤差 < 2 mm
```

**標定數據持久化**:

```python
import pickle

# 儲存標定結果
with open("hand_eye_calibration.pkl", "wb") as f:
    pickle.dump(calibrator.hand_eye_transform, f)

# 載入標定結果
with open("hand_eye_calibration.pkl", "rb") as f:
    transform = pickle.load(f)
    vision.set_hand_eye_transform(transform)
```

---

## 座標轉換

### CoordinateTransform.pixel_to_real()

**目的**: 將像素座標轉換為現實座標

**簽名**:
```python
@staticmethod
def pixel_to_real(
    pixel_x: float,
    pixel_y: float,
    camera_matrix: np.ndarray,
    hand_eye_transform: np.ndarray,
    z_mm: float = 0.0
) -> Tuple[float, float]
```

**輸入參數**:

| 參數 | 類型 | 說明 |
|------|------|------|
| pixel_x | float | 像素 X 座標 (0-640) |
| pixel_y | float | 像素 Y 座標 (0-480) |
| camera_matrix | np.ndarray | 相機矩陣 K (3×3) |
| hand_eye_transform | np.ndarray | Hand-eye 轉換矩陣 (4×4) |
| z_mm | float | Z 座標，預設 0 (檯面高度) |

**輸出**:

```python
(real_x_mm, real_y_mm)  # 現實座標 (mm)
```

**轉換過程**:

```
像素座標 (u, v)
  ↓
正規化座標 (x', y') = K^(-1) @ [u, v, 1]
  ↓
3D 齊次座標 = [x', y', 0, 1]
  ↓
應用 Hand-eye 轉換矩陣
  ↓
世界座標 (X_mm, Y_mm)
```

### CoordinateTransform.calibrate_hand_eye()

**目的**: 從標定點對計算 Hand-eye 轉換矩陣

**簽名**:
```python
@staticmethod
def calibrate_hand_eye(
    pixel_points: List[Tuple[float, float]],
    real_points: List[Tuple[float, float]],
    camera_matrix: np.ndarray
) -> np.ndarray
```

**回傳**: 4×4 齊次轉換矩陣

---

## VisionSystem 主類

### VisionSystem.detect_foods()

**目的**: 檢測食材並直接返回現實座標

**簽名**:
```python
def detect_foods(self, image: np.ndarray) -> List[Dict]
```

**輸出** (與 YOLO 相同，但新增現實座標欄位):

```python
{
    'class_id': int,
    'class_name': str,
    'confidence': float,
    'center_x_pixel': float,
    'center_y_pixel': float,
    'center_x_mm': float,        # ← 新增：現實 X 座標
    'center_y_mm': float,        # ← 新增：現實 Y 座標
    'width_pixel': float,
    'height_pixel': float,
    'angle_deg': float,
}
```

### VisionSystem.get_location_mm()

**目的**: 快速查詢單個食材的現實座標

**簽名**:
```python
def get_location_mm(
    self,
    food_name: str,
    image: np.ndarray
) -> Optional[Tuple[float, float]]
```

**輸入參數**:

| 參數 | 類型 | 說明 |
|------|------|------|
| food_name | str | "CUCUMBER", "CARROT", "CORN" |
| image | np.ndarray | 輸入圖像 |

**輸出**: `(x_mm, y_mm)` 或 `None` 如果未檢測到

**使用範例**:

```python
# 快速查詢小黃瓜位置
location = vision.get_location_mm("CUCUMBER", image)

if location:
    x_mm, y_mm = location
    print(f"小黃瓜位置: ({x_mm:.1f}, {y_mm:.1f})")
else:
    print("未檢測到小黃瓜")
```

---

### VisionSystem.get_location_and_angle_mm()

**簽名**:
```python
def get_location_and_angle_mm(
    self,
    food_name: str,
    image: np.ndarray
) -> Optional[Tuple[float, float, float]]
```

跟 `get_location_mm()` 一樣，但多回傳旋轉角，給 PICKUP 指令即時定位用（2026/8 起 PICKUP 的 X_MM/Y_MM/ANGLE_DEG 就是從這裡來的）。

**輸入參數**:

| 參數 | 類型 | 說明 |
|------|------|------|
| food_name | str | "CUCUMBER", "CARROT", "CORN" |
| image | np.ndarray | 輸入圖像 |

**輸出**: `(x_mm, y_mm, angle_deg)` 或 `None` 如果未檢測到；`angle_deg` 為 0-180°，只有 OBB 模型才是真實量測值（見 `angle_source` 欄位），目前無法分辨食材頭尾方向。

**使用範例**:

```python
detection = vision.get_location_and_angle_mm("CUCUMBER", image)

if detection:
    x_mm, y_mm, angle_deg = detection
    print(f"小黃瓜位置: ({x_mm:.1f}, {y_mm:.1f})，角度: {angle_deg:.1f}°")
else:
    print("未檢測到小黃瓜，不送 PICKUP 指令")
```

---

## 使用範例

### 完整初始化與檢測流程

```python
import cv2
import numpy as np
from vision_skeleton import VisionSystem

# ============================================================================
# 1. 初始化視覺系統
# ============================================================================

vision = VisionSystem()

# ============================================================================
# 2. 相機標定（一次性，或系統啟動時）
# ============================================================================

calibration_image = cv2.imread("calibration_board.jpg")

# 添加標定點（用戶用標尺手工測量、點擊確認）
vision.calibrator.add_calibration_pair(100, 150, 50, 75)
vision.calibrator.add_calibration_pair(200, 250, 100, 125)
vision.calibrator.add_calibration_pair(400, 300, 200, 150)
vision.calibrator.add_calibration_pair(550, 400, 275, 200)
vision.calibrator.add_calibration_pair(300, 150, 150, 75)

# 執行標定
if vision.calibrator.calibrate():
    print("✓ Hand-eye 標定成功")
else:
    print("✗ 標定失敗，請檢查")
    exit()

# ============================================================================
# 3. 運行時食材檢測
# ============================================================================

# 讀取現場圖像
live_image = cv2.imread("live_scene.jpg")

# 檢測所有食材（返回現實座標）
detections = vision.detect_foods(live_image)

print(f"檢測到 {len(detections)} 個食材:")

for det in detections:
    print(f"  - {det['class_name']}: ({det['center_x_mm']:.1f}, {det['center_y_mm']:.1f}) mm")

# ============================================================================
# 4. 單個食材快速查詢
# ============================================================================

cucumber_pos = vision.get_location_mm("CUCUMBER", live_image)

if cucumber_pos:
    x, y = cucumber_pos
    print(f"小黃瓜座標: ({x:.1f}, {y:.1f}) mm")

# ============================================================================
# 5. 檢測 ArUco 基準標記（用於驗證標定）
# ============================================================================

markers = vision.detect_aruco_markers(live_image)

for marker in markers:
    print(f"標記 {marker['marker_id']}: 中心 ({marker['center_x_pixel']:.1f}, {marker['center_y_pixel']:.1f})")
```

### 與 phase_controller 的集成

```python
# phase_controller.py 中的使用

class PhaseController:
    def __init__(self, vision_system: VisionSystem, comms_manager):
        self.vision = vision_system
        self.comms = comms_manager
    
    def execute_pickup_phase(self, food_type: str, image: np.ndarray):
        """
        執行取料階段

        Args:
            food_type: "CUCUMBER", "CARROT", "CORN"
            image: 現場圖像
        """
        # 1. 使用視覺系統取得食材座標＋旋轉角
        detection = self.vision.get_location_and_angle_mm(food_type, image)

        if not detection:
            raise Exception(f"未檢測到食材: {food_type}，不送取料指令")

        x_mm, y_mm, angle_deg = detection

        # 2. 發送取料指令（座標/角度隨指令一起送給雙臂）
        cmd = f'PICKUP,PICKUP_{food_type},F60_F,{x_mm:.2f},{y_mm:.2f},{angle_deg:.2f}'
        self.comms.send_command_dual(cmd)

        # 3. 確認取料完成
        response = self.comms.send_command('F60_F', 'READY,F60_F')

        return detection
```

---

## 常見問題

### Q1: 標定失敗，誤差超過 3mm

**可能原因**:
- 點對數量太少（< 5 對）
- 手工測量精度不足
- 相機鏡頭有灰塵或畸變

**解決方案**:
- 新增更多標定點（10+ 對）
- 使用更精確的標尺和標定方法
- 清潔相機鏡頭
- 重新執行相機內參標定

### Q2: YOLO 檢測信心度低

**可能原因**:
- 光線不足
- 訓練資料不夠
- 食材被遮擋

**解決方案**:
- 改善光線
- 蒐集更多訓練圖像
- 調整信心度閾值（降低至 0.6）

### Q3: ArUco 標記檢測失敗

**可能原因**:
- 標記被食材遮擋
- 標記角度過傾斜
- 標記邊界不清

**解決方案**:
- 放置標記位置遠離取料區
- 確保標記平行於檯面
- 重新打印高對比度的標記

---

## 版本歷史

| 版本 | 日期 | 修改內容 |
|------|------|--------|
| v1.0 | 2026/7/23 | 初版定案 |
| v1.1 | 2026/8/3 | 食材種類改為 CUCUMBER/CARROT/CORN；新增 `get_location_and_angle_mm()` API（PICKUP 視覺定位用） |

---

**文檔維護者**: Wilson + Zhang  
**最後更新**: 2026/8/3
