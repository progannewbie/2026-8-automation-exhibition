# SmartCook 軟體規劃完成總結 (Software Planning Complete)

**日期**: 2026/7/23  
**狀態**: ✅ 軟體設計規劃 100% 完成  
**下一步**: 開始編寫實現代碼

---

## 📊 規劃進度總覽

```
軟體架構規劃
├─ ✅ 配置層 (Config)
│   ├─ config_connection.py ......... TCP 連線參數
│   ├─ config_objects.py ........... 食材/工具/位置定義
│   ├─ config_commands.py .......... 指令格式定義
│   ├─ config_vision.py ........... 視覺系統配置
│   └─ config_phase.py ............ 流程參數配置
│
├─ ✅ 通訊層 (Communication)
│   ├─ comms_connection_skeleton.py . TCP Socket 收發
│   └─ COMMAND_SPECIFICATION.md ..... 9 種指令規範
│
├─ ✅ 視覺層 (Vision)
│   ├─ vision_skeleton.py .......... YOLO + ArUco + Hand-eye
│   └─ VISION_API_SPECIFICATION.md .. 視覺 API 規範
│
├─ ✅ 流程層 (Phase Control)
│   ├─ phase_controller_skeleton.py . 狀態機實現
│   └─ PHASE_CONTROLLER_SPECIFICATION.md ... 流程規範
│
└─ ✅ 主程序層 (Main) — 規劃完成
    └─ MAIN_PROGRAM_SPECIFICATION.md (菜單邏輯、主控流)
```

---

## 📦 已完成的文件清單

### 1. 配置層 (Config) — 5 個文件

| 檔案 | 類型 | 大小 | 說明 |
|------|------|------|------|
| config_connection.py | Python | 5 KB | TCP 參數、握手、心跳、狀態碼 |
| config_objects.py | Python | 8 KB | 食材/工具/位置點定義 (10 點) |
| config_commands.py | Python | 12 KB | 指令定義 (9 種)、菜色食譜 (4 種) |
| config_vision.py | Python | 10 KB | YOLO、ArUco、Hand-eye 配置 |
| config_phase.py | Python | 15 KB | 流程參數、菜色定義、狀態機 |

### 2. 通訊層 (Communication) — 3 個文件

| 檔案 | 類型 | 大小 | 說明 |
|------|------|------|------|
| comms_connection_skeleton.py | Python | 12 KB | TCP Socket、握手、心跳 |
| COMMAND_SPECIFICATION.md | Markdown | 20 KB | 完整指令規範文檔 |
| COMMAND_REFERENCE.csv | CSV | 3 KB | 快速參考表 |

### 3. 視覺層 (Vision) — 4 個文件

| 檔案 | 類型 | 大小 | 說明 |
|------|------|------|------|
| vision_skeleton.py | Python | 14 KB | YOLODetector、ArUcoDetector、VisionSystem |
| VISION_API_SPECIFICATION.md | Markdown | 12 KB | 視覺 API 完整規範 |
| VISION_QUICK_REFERENCE.md | Markdown | 3 KB | 一頁參考卡 |

### 4. 流程層 (Phase Control) — 3 個文件

| 檔案 | 類型 | 大小 | 說明 |
|------|------|------|------|
| phase_controller_skeleton.py | Python | 22 KB | PhaseController 主類 + 狀態機 |
| PHASE_CONTROLLER_SPECIFICATION.md | Markdown | 18 KB | 流程規範 + 4 菜色定義 |

### 5. 主程序層 (Main) — 1 個文件

| 檔案 | 類型 | 大小 | 說明 |
|------|------|------|------|
| MAIN_PROGRAM_SPECIFICATION.md | Markdown | 17 KB | 菜單、主循環、狀態管理規範 |

### 6. 物件定義 — 2 個文件

| 檔案 | 類型 | 大小 | 說明 |
|------|------|------|------|
| OBJECT_DEFINITIONS_v1.1.md | Markdown | 15 KB | 食材、工具、位置點詳細定義 |
| CALIBRATION_POINTS_v1.1.csv | CSV | 2 KB | 10 個標定點檔案 |

---

## 🔑 核心設計決策

### 1. 模組化架構

```
層級        模組              職責
─────────────────────────────────────
Config      config_*.py       參數常數
Comms       comms_*.py        TCP 通訊
Vision      vision_*.py       YOLO + 標定
Phase       phase_*.py        狀態機執行
Main        main.py           菜單 + 循環
```

### 2. 四菜色模式

| 菜色 | 流程 | 時間 | 連續 |
|------|------|------|------|
| 1 | 小黃瓜 → 切 → 盤 | 35s | ✗ |
| 2 | 生菜 → 切 → 盤 | 40s | ✗ |
| 3 | 紅卷須 → 盤 (無切) | 20s | ✗ |
| 4 | 小黃瓜+生菜+紅卷須 → 翻炒 → 盤 | 150s | ✓ |

### 3. 座標系統

```
像素 (640×480)
  ↓ Hand-eye 轉換 (±3mm)
現實 (mm, 檯面左下角原點)
  ↓ 視覺系統
食材座標 + 角度
```

### 4. 指令架構

```
CSV 格式指令 (以 \n 結尾)
  ↓
指令解析 (CommandParser)
  ↓
參數驗證
  ↓
發送機器人 (CommsManager)
  ↓
回應解析 (OK / ERROR / BUSY)
```

### 5. 錯誤策略

```
可重試 (取料、切割、放置):
  失敗 → 等 2秒 → 重試 (3 次) → 失敗 → 終止

不可重試 (復歸、翻炒、最終放盤):
  失敗 → 立即終止 (危險)

連續執行保護 (菜色 4):
  中間失敗 → 無法恢復 → 立即停止
```

---

## 📐 精度指標

| 項目 | 要求 | 備註 |
|------|------|------|
| **YOLO 位置** | ±5 mm | 食材中心點 |
| **YOLO 角度** | ±5° | 食材方向 |
| **Hand-eye** | **±3 mm** | 像素 → 現實轉換 |
| **機器人位置** | ±10 mm | 鏟子位置點 |
| **信心度** | ≥0.7 | YOLO 檢測閾值 |

---

## 🎯 各層 API 入口點

### Config 層

```python
from config_objects import LocationPoint, FoodType, ToolType
from config_commands import MENU, get_recipe_instructions
from config_vision import YOLOConfig, ArUcoConfig
from config_phase import get_phases, FOOD_CUT_PARAMS
```

### Comms 層

```python
from comms_connection_skeleton import CommsManager

comms = CommsManager()
comms.connect_all()
response = comms.send_command("F60_F", "PICKUP,PICKUP_CUCUMBER,F60_F")
```

### Vision 層

```python
from vision_skeleton import VisionSystem

vision = VisionSystem()
location = vision.get_location_mm("CUCUMBER", image)
# 回傳 (x_mm, y_mm) 或 None
```

### Phase 層

```python
from phase_controller_skeleton import PhaseController

controller = PhaseController(vision, comms)
controller.select_menu("4")
success = controller.execute()
controller.print_execution_report()
```

---

## 📝 規劃文檔清單

### 規範文檔 (Markdown)

- ✅ CONNECTION_PROTOCOL.md — TCP 握手、心跳、狀態碼
- ✅ OBJECT_DEFINITIONS_v1.1.md — 食材/工具/位置詳細規範
- ✅ COMMAND_SPECIFICATION.md — 9 種指令完整定義
- ✅ VISION_API_SPECIFICATION.md — YOLO/ArUco/Hand-eye API
- ✅ PHASE_CONTROLLER_SPECIFICATION.md — 流程狀態機規範

### 快速參考 (CSV / 簡短 Markdown)

- ✅ COMMAND_REFERENCE.csv — 指令速查表
- ✅ VISION_QUICK_REFERENCE.md — 視覺 API 一頁卡
- ✅ CALIBRATION_POINTS_v1.1.csv — 10 個標定點表

### Python 骨架代碼 (配置 + 實現)

- ✅ config_*.py — 5 個配置模組
- ✅ *_skeleton.py — 4 個骨架實現

---

## ⏭️ 下一步：實現階段

### 優先順序

```
1️⃣  編寫 main.py 實現
    根據 MAIN_PROGRAM_SPECIFICATION.md 完整實現
    
2️⃣  編寫各模組實現代碼
    config_*.py → comms_*.py → vision_*.py → phase_*.py
    補全 TODO、錯誤處理、日誌
    
3️⃣  YOLO 訓練與標定
    收集 ≥300 張訓練圖像
    Hand-eye calibration 至 ±3mm
    
4️⃣  集成測試
    單模組單元測試
    端到端集成測試
    
5️⃣  現場調試
    實機對接 (F60_F + F60_R)
    實際動作示教
    穩定性測試 (連續 10+ 次)
```

---

## 📚 所有規劃文件位置

所有文件均位於: `/mnt/user-data/outputs/`

```
outputs/
├─ 配置層
│  ├─ config_connection.py
│  ├─ config_objects.py
│  ├─ config_commands.py
│  ├─ config_vision.py
│  └─ config_phase.py
│
├─ 通訊層
│  ├─ comms_connection_skeleton.py
│  ├─ COMMAND_SPECIFICATION.md
│  └─ COMMAND_REFERENCE.csv
│
├─ 視覺層
│  ├─ vision_skeleton.py
│  ├─ VISION_API_SPECIFICATION.md
│  └─ VISION_QUICK_REFERENCE.md
│
├─ 流程層
│  ├─ phase_controller_skeleton.py
│  └─ PHASE_CONTROLLER_SPECIFICATION.md
│
├─ 物件定義
│  ├─ OBJECT_DEFINITIONS_v1.1.md
│  └─ CALIBRATION_POINTS_v1.1.csv
│
├─ 主程序層
│  └─ MAIN_PROGRAM_SPECIFICATION.md
│
└─ 規範文檔
   ├─ CONNECTION_PROTOCOL.md
   └─ SOFTWARE_PLANNING_COMPLETE.md (本檔案)
```

---

## ✅ 檢查清單

軟體設計規劃：
- ✅ 系統架構設計
- ✅ 配置層完整定義
- ✅ 通訊層 API 規範
- ✅ 視覺層 API 規範
- ✅ 流程控制狀態機
- ✅ 四菜色完整流程定義
- ✅ 錯誤重試策略
- ✅ 精度指標確認
- ✅ 座標轉換算法
- ✅ 日誌與監控機制

軟體規劃完整性：
- ✅ 主程序規劃完成 (菜單、主循環、狀態管理)
- ✅ 所有架構文檔完成
- ✅ 依賴關係明確
- ✅ API 設計規範

軟體實現準備：
- ⏳ 代碼實現 (待開始)
- ⏳ YOLO 訓練與標定
- ⏳ 集成測試

---

## 🎓 使用入門

### 快速開始 (30 分鐘)

1. 閱讀本檔案 (5 分)
2. 瀏覽 COMMAND_REFERENCE.csv (5 分)
3. 查看 VISION_QUICK_REFERENCE.md (5 分)
4. 研讀 phase_controller_skeleton.py (10 分)
5. 執行第一個菜色 (5 分)

### 深度學習 (2 小時)

1. COMMAND_SPECIFICATION.md — 指令設計
2. VISION_API_SPECIFICATION.md — 座標轉換
3. PHASE_CONTROLLER_SPECIFICATION.md — 狀態機
4. config_*.py 配置文件

---

## 📞 技術支持

**各模組負責人**:
- **Config/Objects**: Zhang
- **Communications**: Zhang + 硬體工程師
- **Vision**: Wilson + Zhang
- **Phase Control**: Zhang
- **Main Program**: Zhang

**文檔更新日期**: 2026/7/23  
**版本**: v1.0 完整規劃版

---

**Software Planning Status: 100% COMPLETE ✅**

所有規劃文檔已完成，代碼實現待開始！📋→💻
