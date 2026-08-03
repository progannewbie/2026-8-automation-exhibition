"""
SmartCook 連線配置 (Connection Configuration)
連線層參數、IP白名單、TCP協議定義
"""

# ============================================================================
# 1. TCP 連線參數
# ============================================================================

TCP_CONFIG = {
    # F60 機器人控制器連線參數
    'F60_F': {
        'name': 'Left Arm (F60_F)',
        'ip': '192.168.5.2',
        'port': 9000,
        'description': '左臂控制器'
    },
    'F60_R': {
        'name': 'Right Arm (F60_R)',
        'ip': '192.168.5.7',
        'port': 9000,
        'description': '右臂控制器'
    },
}

# IP 白名單 — 防止配置錯誤連到不明 IP
IP_WHITELIST = [
    '192.168.5.2',      # F60_F
    '192.168.5.7',      # F60_R
    '192.168.5.1',      # 交換器 (可選)
    '192.168.5.100',    # PC 自身 (可選)
]

# TCP 連線重試邏輯
TCP_RETRY = {
    'max_retries': 5,           # 最多重試 5 次
    'retry_delay': 1.0,         # 每次重試間隔 1 秒
    'connection_timeout': 5,    # 連線超時 5 秒
    'read_timeout': 30,          # 讀取超時 5 秒
}

# 心跳(Heartbeat)設定
HEARTBEAT = {
    'enabled': True,            # 啟用心跳
    'interval': 3,              # 每 3 秒發一次心跳
    'command': 'HEARTBEAT',     # 心跳指令名
}

# ============================================================================
# 2. CSV 協議定義
# ============================================================================

CSV_PROTOCOL = {
    'line_terminator': '\n',    # 每行結尾用 \n (Unix 風格)
    'delimiter': ',',           # 欄位分隔符
    'encoding': 'utf-8',        # 編碼格式
}

# ============================================================================
# 3. 握手與狀態碼
# ============================================================================

HANDSHAKE = {
    'client_hello': 'connect',  # PC 發給 F60: "connect\n"
    'server_response': 'BOARD_ID',  # F60 回應: "BOARD_ID,{board_id}\n"
}

# F60 回應狀態碼 — comms.py 接收後的標準回應
RESPONSE_STATUS = {
    'OK': {
        'code': 'OK',
        'meaning': '命令執行成功',
        'example': 'OK\n'
    },
    'ERROR': {
        'code': 'ERROR',
        'meaning': '命令執行失敗，帶錯誤碼',
        'example': 'ERROR,E4019\n'  # E4019 是 AS 錯誤碼
    },
    'BUSY': {
        'code': 'BUSY',
        'meaning': '機器人正在執行命令，無法接受新指令',
        'example': 'BUSY\n'
    },
    'STANDBY': {
        'code': 'STANDBY',
        'meaning': '機器人已準備好接受指令',
        'example': 'STANDBY\n'
    },
    'HEARTBEAT_ACK': {
        'code': 'HEARTBEAT_ACK',
        'meaning': '心跳確認',
        'example': 'HEARTBEAT_ACK\n'
    }
}

# ============================================================================
# 4. AS 錯誤碼對應表 (參考 Kawasaki F60 手冊)
# ============================================================================

AS_ERROR_CODES = {
    'E4019': '通訊錯誤 — 接收資料異常',
    'E4020': '通訊超時 — 無回應',
    'E4021': '通訊協議錯誤 — 格式不符',
    'E4022': 'TCP 連線異常',
    'E4023': 'I/O 信號超時',
    # 可依需要擴充
}

# ============================================================================
# 5. comms.py 的連線日誌與診斷
# ============================================================================

LOGGING_CONFIG = {
    'connection_log': 'logs/connection.log',
    'verbose': True,  # 詳細日誌模式
    'log_format': '[%(asctime)s] %(levelname)s | %(message)s',
}

# ============================================================================
# 連線狀態機 (Finite State Machine)
# ============================================================================

CONNECTION_STATES = {
    'DISCONNECTED': '未連線',
    'CONNECTING': '連線中...',
    'HANDSHAKING': '握手中...',
    'READY': '就緒',
    'BUSY': '忙碌中',
    'ERROR': '錯誤',
    'RECONNECTING': '重新連線中...',
}

# ============================================================================
# comms.py 初始化檢查清單
# ============================================================================

INITIALIZATION_CHECKLIST = {
    'check_ip_whitelist': '確認 IP 不在白名單外',
    'check_port_available': '確認 port 9000 未被佔用',
    'check_network_connectivity': '透過 ping 測試網路連通性',
    'test_tcp_connection': '嘗試建立 TCP 連線',
    'perform_handshake': '執行握手流程',
    'validate_board_id': '驗證 F60 Board ID',
    'start_heartbeat': '啟動心跳機制',
}

