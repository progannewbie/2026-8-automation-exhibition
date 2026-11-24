# SmartCook 指令規範 (Command Specification)

**版本**: v1.1  
**日期**: 2026/8/3  
**作者**: Zhang (軟體)  
**狀態**: ✅ 定案

---

## 📋 目錄

1. [指令概述](#指令概述)
2. [動作指令](#動作指令)
3. [控制指令](#控制指令)
4. [查詢指令](#查詢指令)
5. [菜色食譜](#菜色食譜)
6. [指令驗證](#指令驗證)

---

## 指令概述

### 指令分類

| 類別 | 指令 | 用途 |
|------|------|------|
| **動作指令** | PICKUP, CHOP, PLACE, FLIP | 控制機器人動作 |
| **控制指令** | HOME, STOP, RESET | 機器人控制 |
| **查詢指令** | STATUS, READY | 狀態查詢 |

### 指令格式

所有指令都是 CSV 格式，以 `\n` 結尾：

```
<COMMAND_NAME>,<PARAM1>,<PARAM2>,...<PARAMN>\n
```

**例子**:
```
PICKUP,PICKUP_CUCUMBER,F60_F\n
CHOP,CUCUMBER,5,4\n
PLACE,SALAD_BOWL,POUR\n
FLIP,6,50\n
```

---

## 動作指令

### 1. 取料指令 (PICKUP)

**目的**: 使用鏟子從指定位置取料

**格式**（2026/08 更新：新增 X_MM/Y_MM/ANGLE_DEG，食材點位改用 YOLO + 手眼標定即時定位，不再是開機前教死的固定點）:
```
PICKUP,<LOCATION>,<ARM>,<X_MM>,<Y_MM>,<ANGLE_DEG>
```

| 參數 | 類型 | 說明 | 例子 |
|------|------|------|------|
| LOCATION | string | 取料位置 | `PICKUP_CUCUMBER`, `PICKUP_CARROT`, `PICKUP_CORN`, `WAIT_ZONE` |
| ARM | string | 使用的手臂 | `F60_F` (左臂), `F60_R` (右臂) |
| X_MM | float | 食材現實座標 X（mm），只有 `PICKUP_*` 食材點位會用到 | `120.50` |
| Y_MM | float | 食材現實座標 Y（mm），只有 `PICKUP_*` 食材點位會用到 | `80.30` |
| ANGLE_DEG | float | 食材旋轉角（0-180°，來自 YOLO OBB，非 OBB 模型只是估計值） | `45.00` |

**有效位置**:
```python
"PICKUP_CUCUMBER"      # 小黃瓜取料點 — 座標由視覺即時給
"PICKUP_CARROT"        # 紅蘿蔔取料點 — 座標由視覺即時給
"PICKUP_CORN"          # 玉米筍取料點 — 座標由視覺即時給
"WAIT_ZONE"            # 等待區（中間位置）— 固定教點，X/Y/ANGLE 欄位會被 AS 端忽略
```

**X_MM/Y_MM/ANGLE_DEG 的規則**:
- `PICKUP_CUCUMBER`／`PICKUP_CARROT`／`PICKUP_CORN`：送指令前必須先用 `VisionSystem.get_location_and_angle_mm()` 拍照偵測，拿到座標才組指令；**偵測不到就不送指令**，回報錯誤即可，不要用舊教點頂替。
- `WAIT_ZONE` 等固定暫存區：沒有視覺目標，X/Y/ANGLE 傳 `0,0,0` 即可（AS 端會忽略，直接用教點）。

**使用臂規則**:
- 通常使用 `F60_F` (左臂) 進行取料操作
- `F60_R` (右臂) 用於協助固定、壓住食材

**回應**:
```
OK                     # 取料成功
ERROR,<ERROR_CODE>     # 失敗，帶錯誤碼
```

**例子**:
```
PICKUP,PICKUP_CUCUMBER,F60_F,120.50,80.30,45.00
PICKUP,WAIT_ZONE,F60_F,0,0,0
```

---

### 2. 切割指令 (CHOP)

**目的**: 對食材進行切割操作

**格式**:
```
CHOP,<FOOD_TYPE>,<NUM_CUTS>,<CUT_THICKNESS_MM>
```

| 參數 | 類型 | 說明 | 範圍 |
|------|------|------|------|
| FOOD_TYPE | string | 食材類型 | `CUCUMBER`, `CARROT`, `CORN` |
| NUM_CUTS | int | 切割次數 | 1–20 |
| CUT_THICKNESS_MM | float | 切割厚度 (mm) | > 0 |

**食材參數**:

#### CUCUMBER (小黃瓜)

- **方法**: SLICE (縱向切片)
- **推薦切數**: 5 次
- **推薦厚度**: 4 mm

**例子**:
```
CHOP,CUCUMBER,5,4      # 切 5 片，每片 4 mm
```

#### CARROT (紅蘿蔔)

- **方法**: SLICE (縱向切片)
- **推薦切數**: 5 次
- **推薦厚度**: 4 mm

**例子**:
```
CHOP,CARROT,5,4        # 切 5 片，每片 4 mm
```

#### CORN (玉米筍)

- **方法**: SLICE (縱向切片)
- **推薦切數**: 5 次
- **推薦厚度**: 4 mm

**例子**:
```
CHOP,CORN,5,4          # 切 5 片，每片 4 mm
```

**回應**:
```
OK                     # 切割成功
BUSY                   # 機器人忙碌中
ERROR,<ERROR_CODE>     # 失敗
```

---

### 3. 放置指令 (PLACE)

**目的**: 將食材放到指定位置

**格式**:
```
PLACE,<LOCATION>,<METHOD>
```

| 參數 | 類型 | 說明 | 值 |
|------|------|------|------|
| LOCATION | string | 目標位置 | `SALAD_BOWL`, `WAIT_ZONE`, `MIX_ZONE`, `WASTE_CORNER` |
| METHOD | string | 放置方式 | `POUR`, `SCOOP`, `PUSH` |

**有效位置**:

| 位置 | 說明 | 常用方式 |
|------|------|---------|
| `SALAD_BOWL` | 沙拉盤（最終目標） | POUR (倾倒) |
| `WAIT_ZONE` | 等待區（中間暫放） | SCOOP (用鏟放) |
| `MIX_ZONE` | 搅拌區（混合食材） | SCOOP (用鏟放) |
| `WASTE_CORNER` | 廢料角（丟棄部份） | PUSH (推動) |

**放置方式**:

| 方式 | 說明 | 場景 |
|------|------|------|
| `POUR` | 倾倒（雙鏟對合傾倒） | 最終放入沙拉盤 |
| `SCOOP` | 用鏟放置（平放鏟子） | 放到中間位置（等待區、搅拌區） |
| `PUSH` | 推動（推離原位） | 整理廢料 |

**回應**:
```
OK                     # 放置成功
ERROR,<ERROR_CODE>     # 失敗
```

**例子**:
```
PLACE,SALAD_BOWL,POUR  # 倒入沙拉盤
PLACE,WAIT_ZONE,SCOOP  # 放到等待區
PLACE,MIX_ZONE,SCOOP   # 放到搅拌區
PLACE,WASTE_CORNER,PUSH # 推到廢料角
```

---

### 4. 翻炒指令 (FLIP)

**目的**: 對搅拌區的食材進行翻炒混合

**格式**:
```
FLIP,<NUM_CYCLES>,<SPEED_PERCENT>
```

| 參數 | 類型 | 說明 | 範圍 |
|------|------|------|------|
| NUM_CYCLES | int | 翻炒循環數 | 1–20 |
| SPEED_PERCENT | int | 執行速度 (%) | 1–100 |

**參數建議**:

| 參數 | 推薦值 | 說明 |
|------|--------|------|
| NUM_CYCLES | 6–10 | 每個循環約 2–3 秒 |
| SPEED_PERCENT | 30–60 | 太快易撒食材，太慢耗時 |
| 翻起高度 | ≤ 100 mm | 避免過高傷鏟或檯面 |

**翻炒動作描述**:

每個循環：
1. 左鏟向上翻動食材
2. 右鏟向下壓住並翻
3. 雙鏟互補旋轉 ~180°

**回應**:
```
OK                     # 翻炒完成
ERROR,<ERROR_CODE>     # 失敗（如撞到邊界）
```

**例子**:
```
FLIP,6,50              # 翻炒 6 循環，50% 速度（推薦）
FLIP,10,60             # 翻炒 10 循環，60% 速度（較快）
FLIP,8,40              # 翻炒 8 循環，40% 速度（較慢）
```

---

## 控制指令

### 5. 復歸指令 (HOME)

**目的**: 將指定手臂回到安全待機位置

**格式**:
```
HOME,<ARM>
```

| 參數 | 類型 | 值 |
|------|------|------|
| ARM | string | `F60_F` (左臂), `F60_R` (右臂) |

**行為**:
- 機器人以安全速度移動到預定義的 HOME 位置
- 不會碰撞檯面或其他物體
- 通常在初始化和任務結束時調用

**回應**:
```
OK                     # 回到 HOME 成功
ERROR,<ERROR_CODE>     # 失敗
```

**例子**:
```
HOME,F60_F             # 左臂回到 HOME_LEFT
HOME,F60_R             # 右臂回到 HOME_RIGHT
```

---

### 6. 停止指令 (STOP)

**目的**: 緊急停止所有機器人動作

**格式**:
```
STOP
```

**行為**:
- 立即停止兩臂所有動作
- 進入安全待機狀態
- 啟動 I/O 急停信號

**回應**:
```
OK                     # 停止成功
```

**使用場景**:
- 異常偵測（碰撞、越界）
- 用戶按下緊急停止按鈕
- 系統故障

---

### 7. 重置指令 (RESET)

**目的**: 清除所有狀態，重新初始化系統

**格式**:
```
RESET
```

**行為**:
- 清除錯誤狀態
- 回到初始化狀態
- 準備執行新的菜色

**回應**:
```
OK                     # 重置成功
```

---

## 查詢指令

### 8. 狀態查詢 (STATUS)

**目的**: 查詢機器人當前狀態

**格式**:
```
STATUS,<ARM>
```

| 參數 | 類型 | 值 |
|------|------|------|
| ARM | string | `F60_F`, `F60_R` |

**回應**:
```
OK                     # 正常待機
BUSY                   # 正在執行動作
ERROR,<ERROR_CODE>     # 出現錯誤
```

**例子**:
```
STATUS,F60_F           # 查詢左臂狀態
STATUS,F60_R           # 查詢右臂狀態
```

---

### 9. 就緒查詢 (READY)

**目的**: 查詢機器人是否就緒，可接受下一指令

**格式**:
```
READY,<ARM>
```

**回應**:
```
OK                     # 就緒，可發送下一指令
BUSY                   # 忙碌中，請稍候
```

**使用場景**:
- 在發送新指令前檢查機器人狀態
- 實現同步控制

---

## 菜色食譜

### 四種菜色

#### 菜色 1: 小黃瓜單品

```
用戶輸入: 1
指令序列:
  1. PICKUP,PICKUP_CUCUMBER,F60_F
  2. CHOP,CUCUMBER,5,4
  3. PLACE,SALAD_BOWL,POUR
```

**流程時間**: ~30–40 秒

---

#### 菜色 2: 紅蘿蔔單品

```
用戶輸入: 2
指令序列:
  1. PICKUP,PICKUP_CARROT,F60_F
  2. CHOP,CARROT,5,4
  3. PLACE,SALAD_BOWL,POUR
```

**流程時間**: ~30–40 秒

---

#### 菜色 3: 玉米筍單品

```
用戶輸入: 3
指令序列:
  1. PICKUP,PICKUP_CORN,F60_F
  2. CHOP,CORN,5,4
  3. PLACE,SALAD_BOWL,POUR
```

**流程時間**: ~30–40 秒

---

#### 菜色 4: 生菜沙拉完整流程

```
用戶輸入: 4
指令序列（必須連續執行）:

步驟 1: 小黃瓜 → 等待區
  1.1. PICKUP,PICKUP_CUCUMBER,F60_F
  1.2. CHOP,CUCUMBER,5,4
  1.3. PLACE,WAIT_ZONE,SCOOP

步驟 2: 紅蘿蔔 → 搅拌區
  2.1. PICKUP,PICKUP_CARROT,F60_F
  2.2. CHOP,CARROT,5,4
  2.3. PLACE,MIX_ZONE,SCOOP

步驟 3: 等待區小黃瓜 → 搅拌區
  3.1. PICKUP,WAIT_ZONE,F60_F
  3.2. PLACE,MIX_ZONE,SCOOP

步驟 4: 玉米筍 → 搅拌區
  4.1. PICKUP,PICKUP_CORN,F60_F
  4.2. CHOP,CORN,5,4
  4.3. PLACE,MIX_ZONE,SCOOP

步驟 5: 翻炒
  5.1. FLIP,6,50

步驟 6: 倒沙拉盤
  6.1. PLACE,SALAD_BOWL,POUR
```

**流程時間**: ~2–3 分鐘（完整流程）

⚠️ **重要**: 菜色 4 必須連續執行，不能中斷！

---

## 指令驗證

### 參數驗證規則

| 指令 | 驗證項目 | 規則 |
|------|---------|------|
| PICKUP | LOCATION | 必須在有效位置列表中 |
| PICKUP | ARM | 必須是 `F60_F` 或 `F60_R` |
| CHOP | FOOD_TYPE | 必須是 `CUCUMBER`、`CARROT` 或 `CORN` |
| CHOP | NUM_CUTS | 必須 > 0 |
| CHOP | CUT_THICKNESS_MM | 必須 > 0 |
| PLACE | LOCATION | 必須在有效位置列表中 |
| PLACE | METHOD | 必須是 `POUR`, `SCOOP`, 或 `PUSH` |
| FLIP | NUM_CYCLES | 必須 > 0 |
| FLIP | SPEED_PERCENT | 必須 1–100 之間 |

### 錯誤碼表

| 代碼 | 描述 | 原因 |
|------|------|------|
| E4001 | 參數格式錯誤 | CSV 欄位數不對 |
| E4002 | 無效的位置 | LOCATION 不在有效列表 |
| E4003 | 無效的手臂 | ARM 不是 F60_F 或 F60_R |
| E4004 | 無效的食材類型 | FOOD_TYPE 不支援 |
| E4005 | 數值範圍錯誤 | 參數超出有效範圍 |
| E4019 | 通訊錯誤 | 資料格式異常 |
| E4020 | 通訊超時 | F60 無回應 |

---

## Python 使用範例

### 基本指令構建

```python
from config_commands import (
    PickupCommand, ChopCommand, PlaceCommand, FlipCommand,
    get_recipe_instructions, CommandParser
)

# 構建單個指令（X/Y/ANGLE 通常來自 VisionSystem.get_location_and_angle_mm()）
pickup_cmd = PickupCommand.create("PICKUP_CUCUMBER", "F60_F", 120.50, 80.30, 45.00)
print(pickup_cmd)  # 輸出: PICKUP,PICKUP_CUCUMBER,F60_F,120.50,80.30,45.00

chop_cmd = ChopCommand.create("CUCUMBER", 5, 4)
print(chop_cmd)    # 輸出: CHOP,CUCUMBER,5,4

place_cmd = PlaceCommand.create("SALAD_BOWL", "POUR")
print(place_cmd)   # 輸出: PLACE,SALAD_BOWL,POUR
```

### 根據菜單選擇取得食譜

```python
# 用戶輸入 4（生菜沙拉完整流程）
choice = "4"
instructions = get_recipe_instructions(choice)

if instructions:
    print(f"執行菜色 4，共 {len(instructions)} 個指令")
    for i, cmd in enumerate(instructions, 1):
        print(f"  {i}. {cmd}")
```

### 指令解析與驗證

```python
cmd_str = "CHOP,CUCUMBER,5,4"
cmd_name, params = CommandParser.parse(cmd_str)

print(f"命令: {cmd_name}")      # 輸出: CHOP
print(f"參數: {params}")        # 輸出: ['CUCUMBER', '5', '4']

if CommandParser.validate_chop(params):
    print("✓ 指令有效")
else:
    print("✗ 指令無效")
```

---

## 版本歷史

| 版本 | 日期 | 修改內容 |
|------|------|--------|
| v1.0 | 2026/7/23 | 初版定案，支持四菜色模式 |
| v1.1 | 2026/8/3 | PICKUP 新增 X_MM/Y_MM/ANGLE_DEG（食材點位改用 YOLO+手眼標定即時定位）；食材種類統一改為 CUCUMBER/CARROT/CORN，取代舊版的 ROMAINE/RED_LEAF，跟 `config_commands.py`/`config_phase.py`/`.as` 程式對齊 |

---

**文檔維護者**: Zhang  
**最後更新**: 2026/8/3
