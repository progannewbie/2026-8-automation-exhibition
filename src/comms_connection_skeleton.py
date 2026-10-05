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
# 雙臂共用忙碌閘門
# ============================================================================

class BusyGate:
    """
    兩台 F60 共用的「有指令在途」計數器。

    為什麼要共用：DO_PICKUP / DO_CHOP 裡兩臂靠 SYNC_STEP 互等。
    PC 只送指令給 F60_F 時，F60_R 也會卡在 SYNC_STEP 不讀 socket —— 
    但 F60_R 自己的連線上並沒有指令在途。若各自獨立判斷，
    F60_R 的心跳照發不誤、照樣逾時（2026-09-18 14:52:13 就是這個情形）。

    用計數器而非 Event：兩臂可能同時各有一個指令在途，
    先結束的那個不可以把旗標整個放掉。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._count = 0

    def enter(self):
        with self._lock:
            self._count += 1

    def leave(self):
        with self._lock:
            if self._count > 0:
                self._count -= 1

    def is_set(self) -> bool:
        with self._lock:
            return self._count > 0


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
    
    def __init__(self, arm_id: str, busy_gate: Optional['BusyGate'] = None):
        """
        初始化連線物件

        Args:
            arm_id: 'F60_F' 或 'F60_R'
            busy_gate: 兩臂共用的忙碌閘門。由 CommsManager 建立並傳給兩邊，
                       讓任一臂有指令在途時，兩邊都暫停心跳（見 BusyGate 說明）。
                       單獨使用時留 None，會自己建一個私有的。
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

        # 接收緩衝區 — 逾時時「不可」丟棄，否則半行資料會讓後續回應永久錯位。
        # 逾時要丟的是「對方遲到的完整回應」，那個交給 _drain_socket 處理。
        self._rx_buf = b''

        # 指令執行中閘門 — 手臂在跑動作時 AS 端的 recv 迴圈被 SYNC_STEP 卡住，
        # 根本沒空讀 socket，這時候發心跳一定逾時。所以指令在途期間停發心跳。
        # ⚠️ 兩臂共用同一個閘門：SYNC_STEP 會讓「沒收到指令的那一臂」也在忙。
        self._cmd_in_flight = busy_gate if busy_gate is not None else BusyGate()

        # 最後一次成功收發的時間 — 心跳改成「閒置保活」：
        # 線路安靜滿 interval 秒才發，指令頻繁時完全不發。
        self._last_io = time.monotonic()
        
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
                self._rx_buf = b''   # 新連線，舊緩衝一律作廢
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
        心跳迴圈 — 閒置保活

        改寫重點（修正 3，根本解）：
        舊版是「每 interval 秒無條件發一次」。手臂正在跑 DO_PICKUP / DO_CHOP 時，
        AS 端的 recv 迴圈被 SYNC_STEP 擋住不會讀 socket，心跳必定逾時，
        遲到的 ACK 再去污染下一個指令的回應（2026-09-18 生菜沙拉中斷的根因）。

        現在改成兩道閘門：
        1. `_cmd_in_flight` 有指令在途 → 這一拍不發
        2. 線路在 interval 秒內有過收發 → 這一拍不發（不必打擾）

        結果：手臂在動的時候完全安靜，只有真正閒置才保活。
        """
        tick = 0.5   # 用短睡眠輪詢，stop_heartbeat 才能即時生效

        while not self.stop_heartbeat:
            try:
                time.sleep(tick)
                if self.stop_heartbeat:
                    break

                # 閘門 1：有指令在途，手臂正忙，不要打擾
                if self._cmd_in_flight.is_set():
                    continue

                # 閘門 2：線路剛剛才有收發，還不需要保活
                if time.monotonic() - self._last_io < self.heartbeat_interval:
                    continue

                # 發送心跳（與 send_command 共用 socket，須加鎖避免收發交錯）
                with self.socket_lock:
                    # 拿到鎖的瞬間再確認一次：可能有指令正卡在鎖外面等
                    if self._cmd_in_flight.is_set() or self.stop_heartbeat:
                        continue

                    hb_msg = f"{HEARTBEAT['command']}{CSV_PROTOCOL['line_terminator']}"
                    self.socket.sendall(hb_msg.encode(CSV_PROTOCOL['encoding']))

                    # 等待心跳確認
                    response = self._recv_line(timeout=HEARTBEAT.get('ack_timeout', 5))

                    if response and 'HEARTBEAT_ACK' in response:
                        ok = True
                        self._last_io = time.monotonic()
                    else:
                        ok = False
                        # 心跳等不到 ACK：遲到的 ACK 之後還是會回來，
                        # 必須在放掉鎖之前清掉，否則會被下一個指令當成自己的回應。
                        self._drain_socket(reason="心跳逾時")

                if ok:
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

        改寫重點（修正回應流錯位）：
        1. 改用 self._rx_buf 常駐緩衝區。逾時時**保留**已讀到的半行，
           舊版直接丟棄，下次讀會從半行中間接起來，回應永久錯位。
        2. 改成整塊 recv(4096) 再切行，不再逐 byte 讀。
        3. timeout 是「整次呼叫」的總預算，不是單次 recv 的預算。

        Args:
            timeout: 讀取超時秒數，None 則使用 self.read_timeout

        Returns:
            去掉 \n 的字串，或 None 如果接收失敗／逾時
        """
        if not self.socket:
            logger.error(f"[{self.arm_id}] Socket 未初始化")
            return None

        budget = timeout if timeout else self.read_timeout
        deadline = time.monotonic() + (budget if budget else 0)
        old_timeout = self.socket.gettimeout()

        try:
            while True:
                # 緩衝區裡已經有完整一行就直接吐出來，不必再讀 socket
                nl = self._rx_buf.find(b'\n')
                if nl >= 0:
                    line = self._rx_buf[:nl]
                    self._rx_buf = self._rx_buf[nl + 1:]
                    return line.decode(CSV_PROTOCOL['encoding'], errors='replace').strip()

                remain = deadline - time.monotonic()
                if remain <= 0:
                    raise socket.timeout()

                self.socket.settimeout(remain)
                chunk = self.socket.recv(4096)
                if not chunk:
                    logger.error(f"[{self.arm_id}] 連線已關閉")
                    return None
                self._rx_buf += chunk

        except socket.timeout:
            # ⚠️ 這裡刻意不清空 _rx_buf：半行資料要留到下次補齊
            held = len(self._rx_buf)
            if held:
                logger.warning(f"[{self.arm_id}] 讀取超時（緩衝區保留 {held} bytes 半行資料）")
            else:
                logger.warning(f"[{self.arm_id}] 讀取超時")
            return None
        except Exception as e:
            logger.error(f"[{self.arm_id}] 接收異常: {e}")
            return None
        finally:
            try:
                self.socket.settimeout(old_timeout)
            except Exception:
                pass

    def _drain_socket(self, reason: str = "") -> int:
        """
        清空 socket 與緩衝區裡所有還沒讀走的資料。

        用在「這一輪已經放棄等回應」之後 — 對方遲到的回應如果留在管線裡，
        會被下一個指令誤讀成自己的回應，造成回應流永久晚一拍
        （2026-09-18 生菜沙拉中斷的根因）。

        呼叫端必須已經持有 self.socket_lock。

        Returns: 丟棄的 byte 數
        """
        if not self.socket:
            return 0

        dropped = self._rx_buf
        self._rx_buf = b''
        old_timeout = self.socket.gettimeout()

        try:
            self.socket.settimeout(0)   # 非阻塞：把核心緩衝區榨乾
            while True:
                try:
                    chunk = self.socket.recv(4096)
                except (socket.timeout, BlockingIOError):
                    break
                if not chunk:
                    break
                dropped += chunk
        except Exception as e:
            logger.debug(f"[{self.arm_id}] drain 中止: {e}")
        finally:
            try:
                self.socket.settimeout(old_timeout)
            except Exception:
                pass

        if dropped:
            preview = dropped.decode(CSV_PROTOCOL['encoding'], errors='replace').strip()
            logger.warning(
                f"[{self.arm_id}] 清空殘留回應 {len(dropped)} bytes"
                f"{f' ({reason})' if reason else ''}: {preview!r}"
            )
        return len(dropped)

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
        
        # 指令在途期間停發心跳（修正 3）。必須在搶鎖「之前」就舉旗，
        # 這樣已經拿到鎖的心跳線程能在二次確認時看到並讓路。
        self._cmd_in_flight.enter()
        try:
            # 發送指令與接收回應（與心跳線程共用 socket，須加鎖避免收發交錯）
            with self.socket_lock:
                msg = f"{cmd}{CSV_PROTOCOL['line_terminator']}"
                self.socket.sendall(msg.encode(CSV_PROTOCOL['encoding']))
                logger.info(f"[{self.arm_id}] 發送: {cmd}")

                # 讀到遲到的 HEARTBEAT_ACK 就丟掉繼續讀 —— 它是上一輪心跳的回覆，
                # 不是這個指令的回應。舊版直接收下，導致 PICKUP 拿到 HEARTBEAT_ACK
                # 被判定失敗，但手臂其實已經把食材夾走了。
                hb_ack = HEARTBEAT.get('ack', 'HEARTBEAT_ACK')
                deadline = time.monotonic() + self.read_timeout
                response = None
                while True:
                    remain = deadline - time.monotonic()
                    if remain <= 0:
                        break
                    candidate = self._recv_line(timeout=remain)
                    if candidate is None:
                        break
                    if hb_ack in candidate:
                        logger.warning(
                            f"[{self.arm_id}] 丟棄遲到的心跳回覆 {candidate!r}，"
                            f"繼續等 {cmd.split(',')[0]} 的回應"
                        )
                        continue
                    response = candidate
                    break

            if response:
                logger.info(f"[{self.arm_id}] 回應: {response}")
            else:
                logger.error(f"[{self.arm_id}] 等不到 {cmd.split(',')[0]} 的回應")
            return response

        except Exception as e:
            logger.error(f"[{self.arm_id}] 發送異常: {e}")
            return None
        finally:
            # 指令結束：放下旗標，並把心跳的計時重新起算
            # （剛收發完，線路是健康的，不必馬上再戳一次）
            self._last_io = time.monotonic()
            self._cmd_in_flight.leave()
    
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
        self.busy_gate = BusyGate()
        logger.info("CommsManager 初始化")
    
    def connect_all(self) -> bool:
        """
        連線到兩台 F60
        
        Returns:
            True 兩台都連線成功，False 至少一台失敗
        """
        logger.info("正在連線到兩台 F60...")
        
        # 兩臂共用忙碌閘門：任一臂有指令在途，兩邊都停發心跳
        self.busy_gate = BusyGate()
        self.f60_f = F60Connection('F60_F', busy_gate=self.busy_gate)
        self.f60_r = F60Connection('F60_R', busy_gate=self.busy_gate)
        
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

    def send_command_dual(self, cmd) -> Dict[str, Optional[str]]:
        """
        同時送指令給 F60_F 與 F60_R（各自在自己的執行緒平行送出）

        PICKUP / CHOP / PLACE / FLIP 這幾種動作，兩台控制器的 AS 程式會逐
        階段用 SYNC_STEP 訊號互相等待對方。若用 send_command() 依序送（先送
        F60_F、等回應、再送 F60_R），先收到指令的那台會在 SYNC_STEP 卡住等
        對方，而 PC 端又卡在 recv() 等它回應 → 死結，直到 AS 端
        timeout_io_sec(30s) 逾時。所以一定要兩個執行緒同時送出。

        Args:
            cmd: 字串 → 兩臂送同一筆指令
                 dict  → {"F60_F": 指令, "F60_R": 指令} 各臂送各自的指令。
                         PICKUP / HOME 需要這個形式，因為 AS 端會檢查指令裡的
                         arm 欄位是不是自己，送錯會回 ERROR,E4003。

        Returns:
            {"F60_F": 回應或 None, "F60_R": 回應或 None}
        """
        if isinstance(cmd, str):
            cmds = {"F60_F": cmd, "F60_R": cmd}
        else:
            cmds = cmd

        responses: Dict[str, Optional[str]] = {}

        def _call(arm_id: str):
            responses[arm_id] = self.send_command(arm_id, cmds[arm_id])

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

