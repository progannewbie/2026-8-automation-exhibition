# SmartCook 自動化展 — 軟體規劃

SmartCook 展出用機器人烹飪展示系統的軟體規劃文檔與骨架程式碼。

## 目錄結構

```
src/
├─ main.py                        主程序：菜單、主循環、系統協調
├─ config_connection.py           配置層：TCP 參數
├─ config_objects.py              配置層：食材/工具/位置定義
├─ config_commands.py             配置層：指令格式
├─ config_vision.py               配置層：視覺系統配置
├─ config_phase.py                配置層：流程參數、菜色定義
├─ comms_connection_skeleton.py   通訊層：TCP Socket 收發、握手、心跳
├─ vision_skeleton.py             視覺層：YOLO + ArUco + Hand-eye
└─ phase_controller_skeleton.py   流程層：狀態機實現

docs/        規範文檔、快速參考、規劃總結、時間表與腳本 (docx/pdf)

robot/
├─ F60_F_左臂.as   Kawasaki AS 語言：F60_F 左臂 (主切割臂) 控制程式
└─ F60_R_右臂.as   Kawasaki AS 語言：F60_R 右臂 (輔助固定臂) 控制程式
```

所有檔案放在同一層 `src/`，因為彼此以同目錄的方式互相 import
（例如 `from config_phase import MENU`），不是套件式的相對 import。

## 執行

```bash
pip install opencv-python ultralytics numpy
cd src
python main.py
```

YOLO 模型檔案（`models/yolov8_smartcook_v1.pt`，路徑定義於
`config_vision.py`）尚未放入前，`vision_skeleton.py` 會優雅降級：
偵測到套件未安裝或模型檔不存在都只會顯示警告，不會中斷程式，等模型
訓練完成後放入對應路徑即可自動生效，不需修改程式碼。

## 閱讀指南

### 快速查閱 (5 分鐘)

- [docs/SOFTWARE_PLANNING_COMPLETE.md](docs/SOFTWARE_PLANNING_COMPLETE.md) — 本專案總覽
- [docs/COMMAND_REFERENCE.csv](docs/COMMAND_REFERENCE.csv) — 指令速查表
- [docs/VISION_QUICK_REFERENCE.md](docs/VISION_QUICK_REFERENCE.md) — 視覺 API 一頁卡

### 深度理解 (2 小時)

- [docs/COMMAND_SPECIFICATION.md](docs/COMMAND_SPECIFICATION.md) — 9 種指令完整定義
- [docs/VISION_API_SPECIFICATION.md](docs/VISION_API_SPECIFICATION.md) — YOLO/ArUco/Hand-eye API
- [docs/PHASE_CONTROLLER_SPECIFICATION.md](docs/PHASE_CONTROLLER_SPECIFICATION.md) — 流程狀態機規範

### 開發指南 (3 小時)

- `src/config_*.py` 源碼 — 對照 [docs/COMMAND_SPECIFICATION.md](docs/COMMAND_SPECIFICATION.md)、[docs/VISION_API_SPECIFICATION.md](docs/VISION_API_SPECIFICATION.md)
- `src/*_skeleton.py` 源碼 — 對照 [docs/PHASE_CONTROLLER_SPECIFICATION.md](docs/PHASE_CONTROLLER_SPECIFICATION.md)、[docs/CONNECTION_PROTOCOL.md](docs/CONNECTION_PROTOCOL.md)
- [docs/MAIN_PROGRAM_SPECIFICATION.md](docs/MAIN_PROGRAM_SPECIFICATION.md) — 主程序菜單、主循環、狀態管理規範

### 其他參考文檔

- [docs/CONNECTION_PROTOCOL.md](docs/CONNECTION_PROTOCOL.md) — TCP 握手、心跳、狀態碼
- [docs/OBJECT_DEFINITIONS_v1.1.md](docs/OBJECT_DEFINITIONS_v1.1.md) — 食材/工具/位置點詳細定義
- [docs/CALIBRATION_POINTS_v1.1.csv](docs/CALIBRATION_POINTS_v1.1.csv) — 10 個標定點表
- [docs/PLANNING_ROADMAP.txt](docs/PLANNING_ROADMAP.txt) — 規劃路線圖
- [docs/PLANNING_COMPLETE_CHECKLIST.md](docs/PLANNING_COMPLETE_CHECKLIST.md) — 規劃完成檢查清單

### 機器手臂控制程式 (robot/)

- `robot/F60_F_左臂.as` / `robot/F60_R_右臂.as` — Kawasaki AS 語言骨架程式，
  對應 `docs/COMMAND_SPECIFICATION.md`、`docs/CONNECTION_PROTOCOL.md`。
  檔案開頭列出三項待確認事項：乙太網路通訊指令需依控制器韌體版本核對、
  所有教點座標為佔位值 (待 `docs/CALIBRATION_POINTS_v1.1.csv` 標定完成後
  現場教點覆蓋)、雙臂 I/O 訊號腳位待電控工程師依實際配線確認。

## 各模組負責人

- Config / Objects: Zhang
- Communications: Zhang + 硬體工程師
- Vision: Wilson + Zhang
- Phase Control: Zhang
- Main Program: Zhang

## 專案時間表

專案整體時間軸請見 [GitHub Project 看板](https://github.com/users/progannewbie/projects/9)。
