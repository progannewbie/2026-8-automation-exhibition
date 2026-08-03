"""
SmartCook 通訊模組 — 連線層骨架 (comms.py Connection Skeleton)
負責建立、維護、診斷與 F60 機器人的 TCP 連線
"""

import os
import socket
import threading
import time
import logging
from typing import Dict, Tuple, Optional
from config_connection import (
    TCP_CONFIG, TCP_RETRY, HANDSHAKE, HEARTBEAT,
    CSV_PROTOCOL, RESPONSE_STATUS, CONNECTION_STATES,
    IP_WHITELIST, LOGGING_CONFIG
)

# ============================================================================
# 日誌設定
# ============================================================================

os.makedirs(os.path.dirname(LOGGING_CONFIG['connection_log']), exist_ok=True)

logging.basicConfig(
    filename=LOGGING_CONFIG['connection_log'],
    level=logging.DEBUG if LOGGING_CONFIG['verbose'] else logging.INFO,
    format=LOGGING_CONFIG['log_format']
)
logger = logging.getLogger(__name__)

# ============================================================================
# 連線管理類別
# ============================================================================

class F60Connection:
    """
    單一 F60 控制器的連線管理
    
    職責：
    1. TCP 連線建立與重連
    2. 握手流程
    3. 心跳維持
    4. 指令送收（在 CommandParser 中實現）
    """
    
    def __init__(self, arm_id: str):
        """
        初始化連線物件
        
        Args:
            arm_id: 'F60_F' 或 'F60_R'
        """
        self.arm_id = arm_id
        self.config = TCP_CONFIG[arm_id]
        self.ip = self.config['ip']
        self.port = self.config['port']
        
        # 狀態管理
        self.state = CONNECTION_STATES['DISCONNECTED']
        self.socket: Optional[socket.socket] = None
        self.board_id: Optional[str] = None
        
        # 重試邏輯
        self.max_retries = TCP_RETRY['max_retries']
        self.retry_delay = TCP_RETRY['retry_delay']
        self.connection_timeout = TCP_RETRY['connection_timeout']
        self.read_timeout = TCP_RETRY['read_timeout']
        
        # 心跳線程
        self.heartbeat_thread: Optional[threading.Thread] = None
        self.heartbeat_enabled = HEARTBEAT['enabled']
        self.heartbeat_interval = HEARTBEAT['interval']
        self.stop_heartbeat = False

        # 保護 socket 收發，避免心跳線程與指令送收互相干擾
        self.socket_lock = threading.Lock()
        
        logger.info(f"[{self.arm_id}] 連線物件初始化完成")
    
    # ========================================================================
    # 連線建立
    # ========================================================================
    
    def connect(self) -> bool:
        """
        建立 TCP 連線，包含重試邏輯
        
        流程：
        1. IP 白名單檢查
        2. TCP 連線嘗試（最多 max_retries 次）
        3. 握手流程
        4. Board ID 驗證
        5. 心跳啟動
        
        Returns:
            True 連線成功，False 連線失敗
        """
        # 檢查 IP 白名單
        if not self._check_ip_whitelist():
            logger.error(f"[{self.arm_id}] IP {self.ip} 不在白名單中！")
            self.state = CONNECTION_STATES['ERROR']
            return False
        
        # TCP 連線重試
        for attempt in range(1, self.max_retries + 1):
            logger.info(f"[{self.arm_id}] 連線嘗試 {attempt}/{self.max_retries}")
            self.state = CONNECTION_STATES['CONNECTING']
            
            try:
                # 建立 socket
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(self.connection_timeout)
                self.socket.connect((self.ip, self.port))
                
                logger.info(f"[{self.arm_id}] TCP 連線成功")
                
                # 執行握手
                if self._handshake():
                    # 啟動心跳
                    self._start_heartbeat()
                    self.state = CONNECTION_STATES['READY']
                    logger.info(f"[{self.arm_id}] 握手成功，Board ID: {self.board_id}")
                    return True
                else:
                    logger.warning(f"[{self.arm_id}] 握手失敗")
                    self._cleanup()
                    
            except socket.timeout:
                logger.warning(f"[{self.arm_id}] 連線超時 ({self.connection_timeout}s)")
            except ConnectionRefusedError:
                logger.warning(f"[{self.arm_id}] 連線被拒絕")
            except Exception as e:
                logger.error(f"[{self.arm_id}] 連線異常: {e}")
            
            # 重試延遲
            if attempt < self.max_retries:
                logger.info(f"[{self.arm_id}] {self.retry_delay}秒後重試...")
                time.sleep(self.retry_delay)
        
        logger.error(f"[{self.arm_id}] 連線失敗，已達最大重試次數")
        self.state = CONNECTION_STATES['ERROR']
        return False
    
    # ========================================================================
    # 握手流程
    # ========================================================================
    
    def _handshake(self) -> bool:
        """
        執行握手流程
        
        流程：
        1. PC 發送 "connect\n" 給 F60
        2. F60 回應 "BOARD_ID,{board_id}\n"
        3. 驗證 Board ID 格式
        
        Returns:
            True 握手成功，False 握手失敗
        """
        self.state = CONNECTION_STATES['HANDSHAKING']
        
        try:
            # 步驟 1: 發送握手指令
            hello_msg = f"{HANDSHAKE['client_hello']}{CSV_PROTOCOL['line_terminator']}"
            self.socket.sendall(hello_msg.encode(CSV_PROTOCOL['encoding']))
            logger.info(f"[{self.arm_id}] 發送握手: {hello_msg.strip()}")
            
            # 步驟 2: 接收 Board ID
            response = self._recv_line()
            if not response:
                logger.error(f"[{self.arm_id}] 握手無回應")
                return False
            
            # 步驟 3: 解析 Board ID
            parts = response.split(',')
            if len(parts) >= 2 and parts[0] == HANDSHAKE['server_response']:
                self.board_id = parts[1].strip()
                logger.info(f"[{self.arm_id}] 握手成功，Board ID: {self.board_id}")
                return True
            else:
                logger.error(f"[{self.arm_id}] 握手回應格式異常: {response}")
                return False
                
        except Exception as e:
            logger.error(f"[{self.arm_id}] 握手異常: {e}")
            return False
    
    # ========================================================================
    # 心跳機制
    # ========================================================================
    
    def _start_heartbeat(self):
        """
        啟動心跳線程，每 N 秒發送一次心跳
        """
        if not self.heartbeat_enabled:
            return
        
        self.stop_heartbeat = False
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True
        )
        self.heartbeat_thread.start()
        logger.info(f"[{self.arm_id}] 心跳線程已啟動 (間隔: {self.heartbeat_interval}s)")
    
    def _heartbeat_loop(self):
        """
        心跳迴圈 — 定期發送心跳指令
        """
        while not self.stop_heartbeat:
            try:
                time.sleep(self.heartbeat_interval)

                # 發送心跳（與 send_command 共用 socket，須加鎖避免收發交錯）
                with self.socket_lock:
                    hb_msg = f"{HEARTBEAT['command']}{CSV_PROTOCOL['line_terminator']}"
                    self.socket.sendall(hb_msg.encode(CSV_PROTOCOL['encoding']))

                    # 等待心跳確認
                    response = self._recv_line(timeout=2)
                if response and 'HEARTBEAT_ACK' in response:
                    logger.debug(f"[{self.arm_id}] 心跳確認")
                else:
                    logger.warning(f"[{self.arm_id}] 心跳無回應或格式異常")
                    
            except Exception as e:
                logger.error(f"[{self.arm_id}] 心跳異常: {e}")
                break
    
    def _stop_heartbeat(self):
        """
        停止心跳線程
        """
        self.stop_heartbeat = True
        if self.heartbeat_thread:
            self.heartbeat_thread.join(timeout=2)
        logger.info(f"[{self.arm_id}] 心跳線程已停止")
    
    # ========================================================================
    # 收發 CSV 行
    # ========================================================================
    
    def _recv_line(self, timeout: Optional[float] = None) -> Optional[str]:
        """
        接收一行 CSV 資料 (以 \n 結尾)
        
        Args:
            timeout: 讀取超時時間，None 則使用預設值
        
        Returns:
            去掉 \n 的字串，或 None 如果接收失敗
        """
        if not self.socket:
            logger.error(f"[{self.arm_id}] Socket 未初始化")
            return None
        
        try:
            # 設定超時
            old_timeout = self.socket.gettimeout()
            if timeout:
                self.socket.settimeout(timeout)
            
            # 接收資料直到 \n
            line = b''
            while True:
                chunk = self.socket.recv(1)
                if not chunk:
                    logger.error(f"[{self.arm_id}] 連線已關閉")
                    return None
                if chunk == b'\n':
                    break
                line += chunk
            
            # 恢復超時設定
            self.socket.settimeout(old_timeout)
            
            return line.decode(CSV_PROTOCOL['encoding']).strip()
            
        except socket.timeout:
            logger.warning(f"[{self.arm_id}] 讀取超時")
            return None
        except Exception as e:
            logger.error(f"[{self.arm_id}] 接收異常: {e}")
            return None
    
    def send_command(self, cmd: str) -> Optional[str]:
        """
        發送 CSV 指令，接收回應
        
        Args:
            cmd: CSV 格式的指令 (例如 "CHOP,CUCUMBER,5")
        
        Returns:
            回應字串，或 None 如果失敗
        """
        if self.state != CONNECTION_STATES['READY']:
            logger.error(f"[{self.arm_id}] 狀態不是 READY，無法發送指令 (目前: {self.state})")
            return None
        
        try:
            # 發送指令與接收回應（與心跳線程共用 socket，須加鎖避免收發交錯）
            with self.socket_lock:
                msg = f"{cmd}{CSV_PROTOCOL['line_terminator']}"
                self.socket.sendall(msg.encode(CSV_PROTOCOL['encoding']))
                logger.info(f"[{self.arm_id}] 發送: {cmd}")

                response = self._recv_line(timeout=self.read_timeout)
            if response:
                logger.info(f"[{self.arm_id}] 回應: {response}")
            return response
            
        except Exception as e:
            logger.error(f"[{self.arm_id}] 發送異常: {e}")
            return None
    
    # ========================================================================
    # 連線檢查與清理
    # ========================================================================
    
    def _check_ip_whitelist(self) -> bool:
        """檢查 IP 是否在白名單內"""
        return self.ip in IP_WHITELIST
    
    def _cleanup(self):
        """清理連線資源"""
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        self._stop_heartbeat()
    
    def disconnect(self):
        """斷開連線"""
        logger.info(f"[{self.arm_id}] 正在斷開連線...")
        self._cleanup()
        self.state = CONNECTION_STATES['DISCONNECTED']
        logger.info(f"[{self.arm_id}] 已斷開連線")
    
    def is_connected(self) -> bool:
        """檢查連線狀態"""
        return self.state == CONNECTION_STATES['READY']


# ============================================================================
# 雙臂連線管理器
# ============================================================================

class CommsManager:
    """
    管理兩台 F60 的連線
    """
    
    def __init__(self):
        self.f60_f: Optional[F60Connection] = None
        self.f60_r: Optional[F60Connection] = None
        logger.info("CommsManager 初始化")
    
    def connect_all(self) -> bool:
        """
        連線到兩台 F60
        
        Returns:
            True 兩台都連線成功，False 至少一台失敗
        """
        logger.info("正在連線到兩台 F60...")
        
        self.f60_f = F60Connection('F60_F')
        self.f60_r = F60Connection('F60_R')
        
        result_f = self.f60_f.connect()
        result_r = self.f60_r.connect()
        
        if result_f and result_r:
            logger.info("兩台 F60 連線成功！")
            return True
        else:
            logger.error(f"連線失敗 (F60_F: {result_f}, F60_R: {result_r})")
            return False
    
    def disconnect_all(self):
        """斷開兩台 F60 的連線"""
        if self.f60_f:
            self.f60_f.disconnect()
        if self.f60_r:
            self.f60_r.disconnect()
        logger.info("所有連線已關閉")
    
    def send_command(self, arm_id: str, cmd: str) -> Optional[str]:
        """
        發送指令到指定臂
        
        Args:
            arm_id: 'F60_F' 或 'F60_R'
            cmd: CSV 格式指令
        
        Returns:
            回應字串，或 None
        """
        if arm_id == 'F60_F' and self.f60_f:
            return self.f60_f.send_command(cmd)
        elif arm_id == 'F60_R' and self.f60_r:
            return self.f60_r.send_command(cmd)
        else:
            logger.error(f"未知的 arm_id: {arm_id}")
            return None

    def send_command_dual(self, cmd: str) -> Dict[str, Optional[str]]:
        """
        同時送同一筆指令給 F60_F 與 F60_R（各自在自己的執行緒平行送出）

        PICKUP / CHOP / PLACE(POUR) / FLIP 這幾種動作，兩台控制器的 AS
        程式會逐階段用 SYNC_STEP 訊號互相等待對方。若用 send_command()
        依序送（先送 F60_F、等回應、再送 F60_R），等於變相把兩邊的動作
        時間疊加，而且先收到指令的那台會在 SYNC_STEP 卡住等對方，直到
        PC 端真的把指令送到另一邊才會繼續——這裡改用兩個執行緒同時送出，
        兩邊控制器才會幾乎同時進入各自的 SYNC_STEP 交握。

        Returns:
            {"F60_F": 回應或 None, "F60_R": 回應或 None}
        """
        responses: Dict[str, Optional[str]] = {}

        def _call(arm_id: str):
            responses[arm_id] = self.send_command(arm_id, cmd)

        threads = [threading.Thread(target=_call, args=(arm_id,)) for arm_id in ('F60_F', 'F60_R')]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        return responses


# ============================================================================
# 測試用主程式
# ============================================================================

if __name__ == '__main__':
    manager = CommsManager()
    
    # 連線
    if manager.connect_all():
        print("\n✓ 兩台 F60 連線成功！\n")
        
        # 測試發送命令
        # response = manager.send_command('F60_F', 'CHOP,CUCUMBER,5')
        # print(f"回應: {response}\n")
        
        # 斷開
        manager.disconnect_all()
    else:
        print("\n✗ 連線失敗\n")

