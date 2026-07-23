# SmartCook 連線協議規範 (Connection Protocol Specification)

**版本**: v1.0  
**日期**: 2026/7/22  
**作者**: Zhang (軟體)  
**狀態**: ✅ 定案

---

## 📋 目錄

1. [TCP 連線設定](#tcp-連線設定)
2. [CSV 協議格式](#csv-協議格式)
3. [握手流程](#握手流程)
4. [心跳機制](#心跳機制)
5. [狀態碼與錯誤碼](#狀態碼與錯誤碼)
6. [連線狀態機](#連線狀態機)
7. [使用範例](#使用範例)
8. [故障排除](#故障排除)

---

## TCP 連線設定

### 基本參數

| 參數 | 值 | 說明 |
|------|-----|------|
| **F60_F IP** | `192.168.5.2` | 左臂控制器 |
| **F60_R IP** | `192.168.5.7` | 右臂控制器 |
| **Port** | `9000` | 兩台機器人共用 |
| **協議** | TCP | Socket 通訊 |
| **編碼** | UTF-8 | 所有字串編碼 |

### 重試邏輯

| 參數 | 值 | 說明 |
|------|-----|------|
| **最大重試次數** | 5 | 連線失敗後最多重試 5 次 |
| **重試間隔** | 1.0 秒 | 每次重試等待時間 |
| **連線超時** | 5 秒 | TCP `connect()` 超時 |
| **讀取超時** | 5 秒 | 接收回應超時 |

### IP 白名單

防止配置錯誤連到未預期的 IP：

```python
IP_WHITELIST = [
    '192.168.5.2',      # F60_F
    '192.168.5.7',      # F60_R
    '192.168.5.1',      # 交換器 (可選)
    '192.168.5.100',    # PC 自身 (可選)
]
```

任何不在白名單中的 IP 會被拒絕連線。

---

## CSV 協議格式

### 行邊界符號

- **行結尾**: `\n` (Unix 風格，NOT `\r\n`)
- **欄位分隔符**: `,` (逗號)
- **無引號**: CSV 欄位內容不使用引號

### 指令格式

所有指令從 PC 發送給 F60，格式為：

```
<COMMAND_NAME>,<PARAM1>,<PARAM2>,...<PARAMN>\n
```

**示例**:

```
CHOP,CUCUMBER,5
HEARTBEAT
FLIP,3,50
```

### 回應格式

F60 回應格式也是 CSV：

```
<STATUS>,<DETAIL>,<ERROR_CODE>\n
```

**示例**:

```
OK
ERROR,E4019
BUSY
STANDBY
HEARTBEAT_ACK
```

### 指令與回應的區別

| 方向 | 格式 | 例子 |
|------|------|------|
| **PC → F60** | `COMMAND,PARAM\n` | `CHOP,CUCUMBER,5\n` |
| **F60 → PC** | `STATUS[,DETAIL,CODE]\n` | `OK\n` 或 `ERROR,E4019\n` |

---

## 握手流程

### 目標

連線建立後，PC 與 F60 需要進行握手以驗證對方身份，並取得 F60 的 Board ID。

### 流程圖

```
PC (Client)                        F60 (Server)
    |                                  |
    | 1. TCP 連線建立                  |
    |<------ TCP CONNECT ------>|
    |                                  |
    | 2. PC 發送握手指令                |
    |---- "connect\n" ------->|
    |                                  |
    |                          檢查 Board ID
    |                          準備回應
    |                                  |
    | 3. F60 回應 Board ID              |
    |<--- "BOARD_ID,<id>\n" ---|
    |                                  |
    | 4. 驗證格式，握手完成              |
    |                                  |
    | 5. 啟動心跳機制                   |
    |                                  |
    | 連線就緒，可開始發送指令            |
```

### 詳細步驟

#### 步驟 1: TCP 連線

```python
socket.connect(('192.168.5.2', 9000))
socket.settimeout(5)  # 5 秒超時
```

#### 步驟 2: PC 發送握手

```
發送: "connect\n"
```

**Python 代碼**:
```python
msg = "connect\n"
socket.sendall(msg.encode('utf-8'))
```

#### 步驟 3: F60 回應 Board ID

```
回應: "BOARD_ID,F60_CTRL_001\n"
```

**格式**: `BOARD_ID,<board_id>`
- `board_id`: F60 控制器的唯一識別號 (由 F60 AS 程式提供)

#### 步驟 4: 驗證

PC 檢查回應格式：
- 是否以 `BOARD_ID,` 開頭？
- Board ID 不為空？

若驗證失敗，重試握手或斷開連線。

#### 步驟 5: 標記為 READY

連線狀態轉為 `READY`，可開始發送業務指令。

---

## 心跳機制

### 目的

定期檢測連線是否仍然活躍，防止連線被遠端無聲地關閉。

### 設定

| 參數 | 值 | 說明 |
|------|-----|------|
| **啟用** | True | 心跳預設開啟 |
| **間隔** | 3 秒 | 每 3 秒發一次 |
| **指令** | `HEARTBEAT` | 心跳指令名 |
| **回應** | `HEARTBEAT_ACK` | 預期回應 |

### 流程

在後台啟動獨立線程，每 3 秒執行一次：

```
線程: heartbeat_loop()
    [等待 3 秒]
    發送: "HEARTBEAT\n"
    等待回應 (超時 2 秒)
    
    若收到 "HEARTBEAT_ACK\n"
        ✓ 連線活躍
    否則
        ⚠️ 記錄警告，稍候繼續嘗試
```

### 不阻塞業務

心跳在獨立線程運行，不影響主業務指令的收發。

---

## 狀態碼與錯誤碼

### F60 回應狀態碼

| 代碼 | 意義 | 例子 | 動作 |
|------|------|------|------|
| `OK` | 命令執行成功 | `OK\n` | 繼續下一指令 |
| `ERROR` | 命令執行失敗，帶錯誤碼 | `ERROR,E4019\n` | 記錄錯誤，決定重試或放棄 |
| `BUSY` | 機器人忙碌中 | `BUSY\n` | 稍待後重試 |
| `STANDBY` | 機器人就緒 | `STANDBY\n` | 連線就緒，可發送指令 |
| `HEARTBEAT_ACK` | 心跳確認 | `HEARTBEAT_ACK\n` | 連線活躍 |

### AS 錯誤碼對照表

這些錯誤碼由 F60 AS 程式產生，參照 Kawasaki 手冊：

| 代碼 | 描述 | 原因 | 處理 |
|------|------|------|------|
| `E4019` | 通訊錯誤 — 接收資料異常 | 資料格式錯誤，字元損壞 | 檢查 CSV 格式，重試 |
| `E4020` | 通訊超時 — 無回應 | F60 未在時限內回應 | 檢查 F60 狀態，重連 |
| `E4021` | 通訊協議錯誤 — 格式不符 | 指令不符期望格式 | 檢查指令名與參數 |
| `E4022` | TCP 連線異常 | Socket 斷開或重置 | 重新建立連線 |
| `E4023` | I/O 信號超時 | F60 間 I/O 握手超時 | 檢查雙臂 I/O 線路 |

### 連線狀態碼

| 狀態 | 描述 |
|------|------|
| `DISCONNECTED` | 未連線 |
| `CONNECTING` | 正在建立 TCP 連線 |
| `HANDSHAKING` | 正在進行握手 |
| `READY` | 連線就緒，可發送指令 |
| `BUSY` | 機器人執行中 |
| `ERROR` | 連線異常 |
| `RECONNECTING` | 重新連線中 |

---

## 連線狀態機

```
                  connect_all()
                       |
                       v
    +------+    TCP OK   +----------+
    |  TCP  |  -------->  |HANDSHAKE |
    +------+    Fail      +----------+
        ^                       |
        |                       | OK
        |                       v
        |                  +------+
        +----- Error ------|READY |  <-- 業務指令發送/接收
                           +------+
                               |
                          disconnect()
                               |
                               v
                         DISCONNECTED
```

---

## 使用範例

### Python: 連線並發送指令

```python
from comms import CommsManager

# 初始化連線管理器
manager = CommsManager()

# 連線到兩台 F60
if manager.connect_all():
    print("✓ 連線成功")
    
    # 發送指令到左臂
    response = manager.send_command('F60_F', 'CHOP,CUCUMBER,5')
    print(f"回應: {response}")
    
    # 發送指令到右臂
    response = manager.send_command('F60_R', 'FLIP,3,50')
    print(f"回應: {response}")
    
    # 斷開連線
    manager.disconnect_all()
else:
    print("✗ 連線失敗")
```

### 低階 API: 直接操作 Socket

```python
from comms import F60Connection

# 建立左臂連線
left = F60Connection('F60_F')

# 連線
if left.connect():
    # 發送指令
    resp = left.send_command('CHOP,CUCUMBER,5')
    print(f"回應: {resp}")
    
    # 斷開
    left.disconnect()
```

---

## 故障排除

### 連線失敗

**症狀**: `連線失敗，已達最大重試次數`

**檢查清單**:
1. ✓ F60 是否已開啟電源？
2. ✓ 網路線是否連接到正確的交換器？
3. ✓ IP 地址是否正確？ (192.168.5.2, 192.168.5.7)
4. ✓ Port 9000 是否開放？ (AS 程式是否在監聽)
5. ✓ PC 與 F60 是否在同一網段？ (192.168.5.x)

**解決方案**:
```bash
# 測試 IP 連通性
ping 192.168.5.2
ping 192.168.5.7

# 測試 Port 連通性 (需 netcat 或類似工具)
nc -zv 192.168.5.2 9000
```

### 握手失敗

**症狀**: `握手失敗` 或 `握手回應格式異常`

**檢查清單**:
1. ✓ F60 AS 程式是否正常執行？
2. ✓ Board ID 是否被正確設定在 AS 程式中？
3. ✓ CSV 換行符是否為 `\n` (NOT `\r\n`)?

### 心跳無回應

**症狀**: `心跳無回應或格式異常`

**檢查清單**:
1. ✓ 連線是否穩定？(檢查日誌中是否有其他連線錯誤)
2. ✓ F60 是否過載或卡住？
3. ✓ 心跳間隔 (3 秒) 是否太短？

### 指令收不到回應

**症狀**: `讀取超時` 或收不到回應

**檢查清單**:
1. ✓ F60 連線狀態是否為 `READY`？
2. ✓ 指令格式是否正確？ (CSV 格式 + `\n` 結尾)
3. ✓ 讀取超時設定 (5 秒) 是否足夠？

---

## 附錄: 連線流程圖

### 初始化流程

```
main.py
  |
  +---> CommsManager.__init__()
  |
  +---> manager.connect_all()
         |
         +---> F60Connection('F60_F').connect()
         |      ├─ IP 白名單檢查 ✓
         |      ├─ TCP 連線 (重試 5 次) ✓
         |      ├─ 握手 (發 "connect" → 收 "BOARD_ID") ✓
         |      └─ 啟動心跳線程 ✓
         |
         +---> F60Connection('F60_R').connect()
         |      ├─ IP 白名單檢查 ✓
         |      ├─ TCP 連線 (重試 5 次) ✓
         |      ├─ 握手 (發 "connect" → 收 "BOARD_ID") ✓
         |      └─ 啟動心跳線程 ✓
         |
         └---> [連線就緒，進入業務流程]
```

### 業務流程 (發送指令)

```
main.py
  |
  +---> manager.send_command('F60_F', 'CHOP,CUCUMBER,5')
         |
         +---> F60Connection.send_command()
                ├─ 檢查狀態 == 'READY' ✓
                ├─ 發送 CSV 指令 "CHOP,CUCUMBER,5\n"
                ├─ 等待回應 (讀取超時 5 秒)
                └─ 返回回應 "OK\n" 或 "ERROR,E4019\n"
         |
         └---> [根據回應決定下一步]
```

---

## 版本歷史

| 版本 | 日期 | 修改內容 |
|------|------|--------|
| v1.0 | 2026/7/22 | 初版定案 |

---

**文檔維護者**: Zhang  
**最後更新**: 2026/7/22
