# SmartCook 流程控制器規範 (Phase Controller Specification)

**版本**: v1.0  
**日期**: 2026/7/23  
**作者**: Zhang (軟體)  
**狀態**: ✅ 定案

---

## 📋 目錄

1. [架構概述](#架構概述)
2. [菜色食譜](#菜色食譜)
3. [流程階段](#流程階段)
4. [狀態機](#狀態機)
5. [API 文檔](#api-文檔)
6. [使用範例](#使用範例)

---

## 架構概述

### 設計原則

```
菜色選擇 (1/2/3/4)
    ↓
食譜解析 (config_phase.py)
    ↓
階段序列 (Phase Instructions)
    ↓
狀態機執行 (Phase Controller)
    ├─→ 與視覺系統集成 (vision_system)
    ├─→ 與通訊系統集成 (comms_manager)
    ├─→ 錯誤重試
    └─→ 日誌記錄
    ↓
執行報告
```

### 四層架構

| 層級 | 模組 | 職責 |
|------|------|------|
| **Config** | config_phase.py | 食譜、參數定義 |
| **Control** | phase_controller.py | 狀態機、流程執行 |
| **Interface** | comms_manager | 機器人通訊 |
| **Sense** | vision_system | 食材檢測、定位 |

---

## 菜色食譜

### 菜色 1: 小黃瓜單品

```python
菜色 1: 小黃瓜
├─ 取料: PICKUP_CUCUMBER
├─ 切割: CUCUMBER (5 片, 4 mm)
├─ 放置: SALAD_BOWL (倾倒)
└─ 復歸: HOME_LEFT

預估時間: 35 秒
連續執行: ✗ (可中斷)
```

**流程圖**:
```
取料 → 切割 → 放盤 → 復歸 → 完成
```

### 菜色 2: 蘿蔓生菜單品

```python
菜色 2: 蘿蔓生菜
├─ 取料: PICKUP_ROMAINE
├─ 切割: ROMAINE (8 段, 30 mm)
├─ 放置: SALAD_BOWL (倾倒)
└─ 復歸: HOME_LEFT

預估時間: 40 秒
連續執行: ✗ (可中斷)
```

### 菜色 3: 紅卷須單品

```python
菜色 3: 紅卷須
├─ 取料: PICKUP_RED_LEAF
├─ 放置: SALAD_BOWL (倾倒) [不切割]
└─ 復歸: HOME_LEFT

預估時間: 20 秒
連續執行: ✗ (可中斷)
```

### 菜色 4: 生菜沙拉完整流程 ⚠️

```
菜色 4: 生菜沙拉
├─ [1] 小黃瓜 → 等待區
│       ├─ 取料: PICKUP_CUCUMBER
│       ├─ 切割: CUCUMBER (5 片)
│       └─ 放置: WAIT_ZONE (用鏟)
│
├─ [2] 生菜 → 搅拌區
│       ├─ 取料: PICKUP_ROMAINE
│       ├─ 切割: ROMAINE (8 段)
│       └─ 放置: MIX_ZONE (用鏟)
│
├─ [3] 小黃瓜 → 搅拌區
│       ├─ 取料: WAIT_ZONE
│       └─ 放置: MIX_ZONE (用鏟)
│
├─ [4] 紅卷須 → 搅拌區
│       ├─ 取料: PICKUP_RED_LEAF
│       └─ 放置: MIX_ZONE (用鏟)
│
├─ [5] 翻炒
│       └─ FLIP,6,50 (6 循環, 50%)
│
├─ [6] 倒盤
│       └─ 放置: SALAD_BOWL (倾倒)
│
└─ [7] 復歸
        └─ HOME_LEFT

預估時間: 150 秒 (~2.5 分鐘)
連續執行: ✓ (必須連續，不能中斷！)
```

**重要提醒**: 菜色 4 一旦開始，必須全部完成，中間**不允許暫停**。

---

## 流程階段

### 階段定義

| 階段 | 英文 | 說明 | 可重試 |
|------|------|------|--------|
| 取料 | PICKUP | 用鏟子從指定位置取料 | ✓ (3次) |
| 切割 | CHOP | 進行食材切割 | ✓ (3次) |
| 放置 | PLACE | 放到中間位置（等待/搅拌區） | ✓ (3次) |
| 翻炒 | FLIP | 進行翻炒混合 | ✓ (1次) |
| 最終放盤 | PLACE_FINAL | 倒入沙拉盤 | ✗ |
| 復歸 | HOME | 回到待機位置 | ✗ (危險) |

### 階段參數

#### 取料 (PICKUP)

```python
{
    "action": "PICKUP",
    "location": "PICKUP_CUCUMBER",  # 取料點
    "params": {
        "arm": "F60_F",             # 取料手臂（通常左臂）
    },
    "retries": 3,                   # 重試次數
    "timeout_sec": 30.0,            # 超時時間
}
```

#### 切割 (CHOP)

```python
{
    "action": "CHOP",
    "location": "WORK_CHOP_ZONE",
    "params": {
        "food_type": "CUCUMBER",    # 食材類型
        "num_cuts": 5,              # 切割次數
        "cut_thickness_mm": 4.0,    # 厚度
        "holding_arm": "F60_R",     # 壓住臂
    },
    "retries": 3,
    "timeout_sec": 30.0,
}
```

#### 翻炒 (FLIP)

```python
{
    "action": "FLIP",
    "location": "MIX_ZONE",
    "params": {
        "num_cycles": 6,            # 循環次數
        "speed_percent": 50,        # 速度百分比
        "duration_sec": 18.0,       # 預估時間
    },
    "retries": 1,                   # 翻炒一般不重試
    "timeout_sec": 30.0,
}
```

---

## 狀態機

### 狀態轉移圖

```
INIT
  ↓
PICKUP ← ─┐
  ↓       │
CHOP      │ (可重複取料)
  ↓       │
PLACE ────┘
  ↓
FLIP (可選)
  ↓
PLACE_FINAL
  ↓
HOME
  ↓
DONE
```

### 有效轉移

```python
INIT         → [PICKUP]
PICKUP       → [CHOP, PLACE]
CHOP         → [PLACE, PLACE_FINAL]
PLACE        → [PICKUP, FLIP, PLACE_FINAL]
FLIP         → [PLACE_FINAL]
PLACE_FINAL  → [HOME]
HOME         → [DONE]
DONE         → []
```

### 執行狀態

```python
class PhaseStatus(Enum):
    PENDING  = "待執行"
    RUNNING  = "執行中"
    SUCCESS  = "成功"
    FAILED   = "失敗"
    RETRY    = "重試"
```

---

## API 文檔

### PhaseController 主類

#### __init__()

```python
controller = PhaseController(
    vision_system=vision,
    comms_manager=comms
)
```

**參數**:
- `vision_system`: VisionSystem 實例
- `comms_manager`: CommsManager 實例

---

#### select_menu()

**目的**: 選擇菜色

```python
success = controller.select_menu("4")
```

**參數**:
- `choice` (str): "1", "2", "3", "4"

**回傳**: `True` 成功, `False` 無效選擇

**副作用**:
- 載入食譜
- 設置階段序列
- 顯示菜色信息

---

#### execute()

**目的**: 執行整個菜色流程

```python
success = controller.execute()

if success:
    print("✓ 菜色完成")
    controller.print_execution_report()
else:
    print("✗ 菜色失敗")
```

**回傳**: `True` 完成, `False` 失敗

**流程**:
1. 初始化手臂 (STATUS 查詢)
2. 逐階段執行
3. 錯誤自動重試 (3 次)
4. 記錄日誌
5. 列印報告

---

#### get_progress()

**目的**: 取得執行進度

```python
progress = controller.get_progress()
# {
#     "total_phases": 11,
#     "completed_phases": 5,
#     "progress_percent": 45.5,
#     "current_phase": "CHOP",
# }
```

**回傳**: 進度字典

---

#### print_execution_report()

**目的**: 列印執行報告

```python
controller.print_execution_report()
```

**輸出範例**:
```
============================================================
執行報告
============================================================
成功: 11/11

  [1]  ✓ PICKUP         (2.3s)
  [2]  ✓ CHOP           (8.1s)
  [3]  ✓ PLACE          (3.2s)
  ...
  [11] ✓ HOME           (1.5s)

總耗時: 35.2 秒
============================================================
```

---

## 使用範例

### 基本用法

```python
from phase_controller_skeleton import PhaseController
from vision_skeleton import VisionSystem
from comms_connection_skeleton import CommsManager

# 初始化系統
vision = VisionSystem()
comms = CommsManager()
controller = PhaseController(vision, comms)

# 連接機器人
comms.connect_all()

# 選擇菜色 4 (生菜沙拉完整流程)
if not controller.select_menu("4"):
    print("菜色選擇失敗")
    exit()

# 執行
success = controller.execute()

# 報告
if success:
    controller.print_execution_report()
    print("✓ 表演成功！")
else:
    print("✗ 表演失敗")
    controller.print_execution_report()

# 斷開連接
comms.disconnect_all()
```

### 與 main.py 的集成

```python
# main.py 中

class SmartCookApp:
    def __init__(self):
        self.vision = VisionSystem()
        self.comms = CommsManager()
        self.phase_controller = PhaseController(self.vision, self.comms)
    
    def run(self):
        """主程序"""
        # 初始化
        if not self.comms.connect_all():
            print("✗ 連接失敗")
            return
        
        # 菜單循環
        while True:
            print("\n菜單：")
            print("  1. 小黃瓜")
            print("  2. 生菜")
            print("  3. 紅卷須")
            print("  4. 生菜沙拉（完整流程）")
            print("  q. 退出")
            
            choice = input("選擇 (1-4, q): ").strip()
            
            if choice == "q":
                break
            
            if choice not in ["1", "2", "3", "4"]:
                print("✗ 無效選擇")
                continue
            
            # 執行菜色
            if self.phase_controller.select_menu(choice):
                if self.phase_controller.execute():
                    self.phase_controller.print_execution_report()
                else:
                    print("✗ 執行失敗，請檢查日誌")
        
        # 清理
        self.comms.disconnect_all()
```

---

## 錯誤處理

### 重試機制

**可重試動作**:
- PICKUP (3 次重試)
- CHOP (3 次重試)
- PLACE (3 次重試)

**重試策略**:
```
失敗 → 等待 2 秒 → 重試 → 失敗 → ... (最多 3 次)
```

**不可重試動作** (立即失敗):
- FLIP (翻炒失敗無法恢復)
- HOME (復歸失敗→危險)
- PLACE_FINAL (最終放盤失敗)

### 連續執行保護 ⚠️

菜色 4 (生菜沙拉) 設置了 `continuous=True` 標誌：

```python
if self.is_continuous:
    if phase_execution_fails:
        logger.error("✗ 連續執行模式，無法恢復")
        return False  # 立即停止，不嘗試修復
```

任何階段失敗，整個流程終止。

---

## 日誌與監控

### 階段日誌結構

```python
@dataclass
class PhaseLog:
    phase: Phase                # 階段
    status: PhaseStatus         # 執行結果
    start_time: float           # 開始時間
    end_time: Optional[float]   # 結束時間
    duration_sec: Optional[float] # 耗時
    error_msg: Optional[str]    # 錯誤信息
    retry_count: int            # 重試次數
```

### 日誌輸出

```
[1/11] 階段: PICKUP
  取料: PICKUP_CUCUMBER (臂: F60_F)
  ✓ 取料成功

[2/11] 階段: CHOP
  切割: CUCUMBER (5 次，4.0 mm)
  ✓ 切割完成

...

============================================================
執行報告
============================================================
成功: 11/11
總耗時: 150.3 秒
============================================================
```

---

## 版本歷史

| 版本 | 日期 | 修改內容 |
|------|------|--------|
| v1.0 | 2026/7/23 | 初版定案，支持四菜色 + 狀態機 |

---

**文檔維護者**: Zhang  
**最後更新**: 2026/7/23
