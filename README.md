# SmartCook 自動化展

SmartCook 展出用雙臂機器人烹飪展示系統：Kawasaki F60 雙臂搭配 YOLO 視覺定位，
完成小黃瓜、紅蘿蔔、羅曼生菜的夾取、切割、擺盤與生菜沙拉完整流程。

## 系統架構

```
展場觸控介面 (web_ui.py)  ─┐
                           ├─► 流程狀態機 ─► TCP 通訊 ─► F60_F 左臂 / F60_R 右臂 (AS 程式)
終端機主程式 (main.py)    ─┘        ▲
                                    └── 視覺：YOLO + HSV 色彩定位 + ArUco / Hand-eye
```

## 目錄結構

```
src/                               主程式（所有模組放同一層，以同目錄方式互相 import）
├─ web_ui.py                       展場觸控介面（Flask），展出時使用的入口
├─ templates/index.html            觸控介面頁面
├─ main.py                         終端機版主程序：菜單、主循環、統計
├─ config_connection.py            配置層：TCP 參數
├─ config_objects.py               配置層：食材/工具/位置定義
├─ config_commands.py              配置層：指令格式
├─ config_vision.py                配置層：視覺系統配置（模型路徑、類別表）
├─ config_phase.py                 配置層：流程參數、菜色定義 (MENU)
├─ comms_connection_skeleton.py    通訊層：TCP Socket 收發、握手、心跳
├─ vision_skeleton.py              視覺層：YOLO + ArUco + Hand-eye
├─ img_processing.py               視覺層：HSV 色彩分割、頭尾判斷、0–360° 角度修正
├─ phase_controller_skeleton.py    流程層：狀態機實現
├─ models/yolo26_smartcook_v4.pt   YOLO 模型（v4）
├─ models/test_full_result.py      模型結果驗證腳本（來自 YOLO 訓練專案）
├─ 座標/                           座標標定用影像與紀錄 (座標.txt)
└─ logs/                           執行日誌（自動建立）

robot/                             Kawasaki AS 語言手臂程式
├─ F60_F_左臂*.as                  左臂（主切割臂）
├─ F60_R_右臂*.as                  右臂（輔助固定臂）
├─ 原程式/                         原廠/原始程式 rs_f.as、rs_r.as
└─ 連線測試/                       雙臂 TCP 連線測試程式

docs/                              規範文檔、快速參考、標定點、時間表與展出腳本 (docx/pdf)
test/                              各功能測試腳本與攝影機擷取影像
automation-2026-yolo-main/         YOLO 訓練專案：資料集、標註、訓練/驗證腳本、檯面清潔檢查
座標/                              手臂座標與視覺座標對照表 (xlsx)
requirements.txt                   Python 套件清單
```

舊版本（`test0819/` 的 8/19 src 快照與 v1～v3 模型、`robot/robot/` 的 8 月初手臂程式）
已從工作目錄移除，可從 git 第一個 commit「初始快照」取回，例如：

```bash
git checkout a3f792a -- test0819
```

### 手臂程式版本

| 後綴 | 說明 |
|---|---|
| （無） | 主版本 |
| `_GBK` | GBK 編碼版本（供控制器載入中文註解） |
| `_slow` | 降速版本 |
| `修正` | 7/31 的早期修正版 |

## 菜色

定義在 [src/config_phase.py](src/config_phase.py) 的 `MENU`：

1. 小黃瓜：夾取 → 放置 → 切割 → 夾取 → 擺盤 → 回原點
2. 紅蘿蔔：同上
3. 羅曼生菜：夾取 → 直接放入混拌區 → 回原點
4. 生菜沙拉完整流程：多種食材依序切割、翻轉 (FLIP)、擺盤

流程階段：`INIT → PICKUP → PLACE / PLACE_FINAL → CHOP / FLIP → … → HOME`

## 視覺

- 模型：`src/models/yolo26_smartcook_v4.pt`（路徑定義於 [src/config_vision.py](src/config_vision.py)）
- 類別：`CUCUMBER`、`CORN`、`CARROT`、`LETTUCE`、`CUCUMBER_SLICE`（v4 新增）
- YOLO OBB 的角度只有 0–180° 週期，`img_processing.py` 會在 YOLO 框內用 HSV
  色域判斷食材頭尾，補成完整 0–360° 角度。目前 HSV 色域有 cucumber / carrot 兩組。
- 套件未安裝或模型檔不存在時，`vision_skeleton.py` 只會顯示警告、不會中斷程式。

## 安裝與執行

```bash
pip install -r requirements.txt
```

> ultralytics 會連帶安裝 PyTorch（CPU 版約 1GB）。控制電腦若有獨顯，先依 pytorch.org
> 安裝對應 CUDA 版本的 torch，再裝其他套件。

### 展場觸控介面（主要使用方式）

```bash
cd src
python web_ui.py                 # 連接實體手臂
python web_ui.py --simulate      # 不連手臂，純測介面（任何電腦都能跑）
python web_ui.py --host 0.0.0.0  # 讓平板/手機連進來
python web_ui.py --port 8080     # 改用其他埠（預設 5000）
```

啟動後用瀏覽器全螢幕開 <http://localhost:5000> 當觸控畫面。

> ⚠️ 介面上的「停止」鍵只會在階段與階段之間生效（例如切割階段約需 4 分鐘，
> 按下後會等該階段跑完才停）。**它不是安全裝置，緊急停止請使用實體急停按鈕。**

### 終端機版主程式

```bash
cd src
python main.py
```

日誌一律寫到 `src/logs/`（`web_ui_*.log`、`smartcook_*.log`、`connection.log`），
不受執行時所在目錄影響。

## 測試腳本 (test/)

| 腳本 | 用途 |
|---|---|
| `connection_test.py` | TCP 連線測試 |
| `test_io.py` | I/O 訊號測試 |
| `camera_test.py`、`yolo_camera_test.py` | 攝影機與 YOLO 即時偵測 |
| `test_vision_coord.py` | 視覺座標轉換 |
| `test_pickup.py`、`test_pickup_fixed.py` | 夾取 |
| `test_pickup_chop.py` | 夾取 + 切割 |
| `test_flip.py` | 翻轉 |
| `test_full_salad_workflow.py` | 沙拉完整流程（流程邏輯） |
| `test_full_salad_real.py` | 沙拉完整流程（實機） |

攝影機擷取影像存放於 `test/captures/`。

## 文件導覽

### 快速查閱

- [docs/SOFTWARE_PLANNING_COMPLETE.md](docs/SOFTWARE_PLANNING_COMPLETE.md) — 專案總覽
- [docs/COMMAND_REFERENCE.csv](docs/COMMAND_REFERENCE.csv) — 指令速查表
- [docs/VISION_QUICK_REFERENCE.md](docs/VISION_QUICK_REFERENCE.md) — 視覺 API 一頁卡

### 規格

- [docs/COMMAND_SPECIFICATION.md](docs/COMMAND_SPECIFICATION.md) — 指令完整定義
- [docs/CONNECTION_PROTOCOL.md](docs/CONNECTION_PROTOCOL.md) — TCP 握手、心跳、狀態碼
- [docs/VISION_API_SPECIFICATION.md](docs/VISION_API_SPECIFICATION.md) — YOLO / ArUco / Hand-eye API
- [docs/PHASE_CONTROLLER_SPECIFICATION.md](docs/PHASE_CONTROLLER_SPECIFICATION.md) — 流程狀態機
- [docs/MAIN_PROGRAM_SPECIFICATION.md](docs/MAIN_PROGRAM_SPECIFICATION.md) — 主程序菜單、主循環、狀態管理
- [docs/OBJECT_DEFINITIONS_v1.1.md](docs/OBJECT_DEFINITIONS_v1.1.md) — 食材/工具/位置點定義
- [docs/CALIBRATION_POINTS_v1.1.csv](docs/CALIBRATION_POINTS_v1.1.csv) — 標定點表

### 專案管理（docx / pdf）

- `SmartCook_TCP協定規格.docx`、`SmartCook_信號分配表.docx`、`SmartCook_術語字典.docx`
- `SmartCook_展出場景腳本_V3.docx`、`SmartCook_食材視覺策略.docx`
- `SmartCook_專案時間表_v5.1_進度指標版.docx`
- [docs/PLANNING_ROADMAP.txt](docs/PLANNING_ROADMAP.txt)、[docs/PLANNING_COMPLETE_CHECKLIST.md](docs/PLANNING_COMPLETE_CHECKLIST.md)

被取代的舊版文件放在 [docs/archive/](docs/archive/README.md)。

## 各模組負責人

- Config / Objects: Zhang
- Communications: Zhang + 硬體工程師
- Vision: Wilson + Zhang
- Phase Control: Zhang
- Main Program / Web UI: Zhang

## 專案時間表

專案整體時間軸請見 [GitHub Project 看板](https://github.com/users/progannewbie/projects/9)。
