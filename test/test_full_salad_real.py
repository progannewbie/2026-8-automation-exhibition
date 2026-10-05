#!/usr/bin/env python3
"""
完整三菜沙拉工作流程 - 實際機器人控制
使用正確的指令格式和握手協議
"""

import socket
import threading
import time
import sys
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"


class RobotController:
    """機器人 TCP 控制器"""

    def __init__(self, host_f60f="192.168.5.2", port_f60f=9000,
                 host_f60r="192.168.5.7", port_f60r=9000):
        self.host_f60f = host_f60f
        self.port_f60f = port_f60f
        self.host_f60r = host_f60r
        self.port_f60r = port_f60r
        self.sock_f60f = None
        self.sock_f60r = None
        self.step = 0
        # 各臂的收訊緩衝：TCP 是位元組串流，一次 recv 不保證剛好是一整行
        self.rxbuf = {"F60_F": b"", "F60_R": b""}

        # 每次執行開一個新的 log 檔，檔名帶時間戳
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.log_path = LOG_DIR / f"salad_run_{time.strftime('%Y%m%d_%H%M%S')}.log"
        self.log_file = open(self.log_path, "w", encoding="utf-8")
        self.out(f"# log: {self.log_path}")

    def out(self, msg: str = ""):
        """同時輸出到畫面與 log 檔（不加時間戳）"""
        print(msg)
        self.log_file.write(msg + "\n")
        self.log_file.flush()   # 逐行 flush，中途斷線/當掉也保得住紀錄

    def log(self, msg: str):
        """輸出帶時間戳的訊息"""
        ts = time.strftime("%H:%M:%S")
        self.out(f"[{ts}] {msg}")

    def recv_line(self, name: str, sock, timeout: float) -> str:
        """
        收一整行（以 \\n 為界），多收到的留在緩衝區

        AS 端 SEND_LINE 每則訊息結尾都有 \\n。直接用 recv(256) 當一則訊息有
        兩個風險：一是回應被拆成兩個封包只收到半行；二是逾時後遲到的回應
        會被下一個指令誤收，之後每一步的回應都對錯指令 → 整串錯位。
        """
        deadline = time.monotonic() + timeout
        while b"\n" not in self.rxbuf[name]:
            remain = deadline - time.monotonic()
            if remain <= 0:
                raise socket.timeout()
            sock.settimeout(remain)
            chunk = sock.recv(256)
            if not chunk:
                raise ConnectionError("對方關閉了連線")
            self.rxbuf[name] += chunk

        line, _, rest = self.rxbuf[name].partition(b"\n")
        self.rxbuf[name] = rest
        return line.decode("utf-8", errors="replace").strip()

    def connect_and_handshake(self):
        """連接並握手"""
        self.log("正在連接 F60_F...")
        try:
            self.sock_f60f = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock_f60f.connect((self.host_f60f, self.port_f60f))
            self.log("✓ F60_F TCP 連接成功")
        except Exception as e:
            self.log(f"✗ F60_F 連接失敗: {e}")
            return False

        self.log("正在連接 F60_R...")
        try:
            self.sock_f60r = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock_f60r.connect((self.host_f60r, self.port_f60r))
            self.log("✓ F60_R TCP 連接成功")
        except Exception as e:
            self.log(f"✗ F60_R 連接失敗: {e}")
            return False

        # 握手（按順序）
        self.log("\n正在握手...")
        try:
            self.sock_f60f.sendall(b"connect\n")
            resp_f60f = self.recv_line("F60_F", self.sock_f60f, 5)
            self.log(f"  F60_F: {resp_f60f}")

            self.sock_f60r.sendall(b"connect\n")
            resp_f60r = self.recv_line("F60_R", self.sock_f60r, 5)
            self.log(f"  F60_R: {resp_f60r}")

            if "BOARD_ID" in resp_f60f and "BOARD_ID" in resp_f60r:
                self.log("✓ 握手成功\n")
                return True
            else:
                self.log("✗ 握手失敗")
                return False

        except Exception as e:
            self.log(f"✗ 握手錯誤: {e}")
            return False

    def send_cmd(self, cmd: str, timeout: float = 90.0):
        """
        同時送指令給兩臂（各自一條執行緒）

        AS 端 DO_PICKUP / DO_CHOP / DO_FLIP 每個階段都有 SYNC_STEP：
        送出自己的訊號後等對方的訊號。若依序送（送 F60_F、等回應、再送
        F60_R），先收到指令的那台會卡在 SYNC_STEP 等對方，而 PC 又卡在
        recv() 等它回應 → 死結，直到 AS 端 timeout_io_sec(30s) 逾時。
        所以一定要兩條執行緒同時送出。
        """
        self.step += 1

        # 依各臂 AS 程式的參數檢查，調整帶給對方的 arm 欄位
        cmd_f60f, cmd_f60r = self._per_arm(cmd)
        if cmd_f60f == cmd_f60r:
            self.log(f"【步驟 {self.step}】{cmd_f60f}")
        else:
            self.log(f"【步驟 {self.step}】F60_F: {cmd_f60f} / F60_R: {cmd_f60r}")

        results = {}

        def _tx(name, sock, text):
            try:
                sock.sendall((text + "\n").encode())
                results[name] = self.recv_line(name, sock, timeout)
            except socket.timeout:
                results[name] = "TIMEOUT"
            except Exception as e:
                results[name] = f"EXCEPTION: {e}"

        threads = [
            threading.Thread(target=_tx, args=("F60_F", self.sock_f60f, cmd_f60f)),
            threading.Thread(target=_tx, args=("F60_R", self.sock_f60r, cmd_f60r)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.log(f"  F60_F: {results['F60_F']}")
        self.log(f"  F60_R: {results['F60_R']}")

        success = results["F60_F"] == "OK" and results["F60_R"] == "OK"
        self.log("✓ 成功\n" if success else "✗ 失敗\n")
        return success

    @staticmethod
    def _per_arm(cmd: str):
        """
        產生各臂專屬的指令字串

        PICKUP: 左臂 AS 檢查 arm=="F60_F"，右臂 AS 檢查 arm=="F60_R"
        HOME:   各臂 AS 檢查 arm==$this_arm
        其餘指令兩臂共用同一字串
        """
        if cmd.startswith("PICKUP,"):
            f = cmd.replace(",F60_R,", ",F60_F,")
            r = cmd.replace(",F60_F,", ",F60_R,")
            return f, r
        if cmd.startswith("HOME"):
            return "HOME,F60_F", "HOME,F60_R"
        return cmd, cmd

    def run(self):
        """執行完整流程"""
        self.out("="*70)
        self.out("完整三菜沙拉工作流程 - 實時機器人控制")
        self.out("="*70 + "\n")

        if not self.connect_and_handshake():
            return False

        self.out("配置：x=0, y=0, angle=0（固定參數）")
        self.out("切割區與混拌區教的是同一個座標，切完不搬就等於已經在混拌區")
        self.out("食材長 170mm，切 15 刀 × 5mm = 前段 75mm，尾段不切")
        self.out("  小黃瓜  ：取料 → 切割區 → 切 15 刀 5mm → 夾起 → 暫放區1（讓出切割區）")
        self.out("  紅蘿蔔  ：取料 → 切割區 → 切 15 刀 5mm →（留在原地＝混拌區）")
        self.out("  羅曼生菜：取料 → 混拌區（不切）")
        self.out("  取回    ：暫放區1 → 混拌區\n")

        time.sleep(1)

        # ===== 小黃瓜：取料 → 送進切割區 → 切 → 暫放區1 =====
        self.out("【小黃瓜】")
        if not self.send_cmd("PICKUP,PICKUP_CUCUMBER,F60_F,0,0,0"):
            self.emergency_home()
            return False
        time.sleep(2)

        if not self.send_cmd("PLACE,PICKUP_CUCUMBER,WORK_CHOP_ZONE,SCOOP"):
            self.emergency_home()
            return False
        time.sleep(2)

        # 步進值必須是 5 — 左臂的下刀位置是絕對教點 chop_1[i]（固定 5mm 間距），
        # 右臂則是靠 DRAW .thick 累加。兩者不一致的話右臂會壓不到食材。
        # 15 刀 × 5mm = 75mm，約 4 分鐘（實測 5 刀 79 秒），逾時要放到 420 秒。
        if not self.send_cmd("CHOP,CUCUMBER,15,5", timeout=420):
            self.emergency_home()
            return False
        time.sleep(2)

        # 切完食材是躺在檯面上的，要先 PICKUP 夾起來才能搬走。
        # DO_PICKUP 沒有 WORK_CHOP_ZONE 分支，但 mix_zone 跟 work_zone 教的是
        # 同一個座標（536.225, 447.456, -327.126），所以用 MIX_ZONE 這條分支。
        if not self.send_cmd("PICKUP,MIX_ZONE,F60_F,0,0,0"):
            self.emergency_home()
            return False
        time.sleep(2)

        if not self.send_cmd("PLACE,MIX_ZONE,WAIT_ZONE_1,SCOOP"):
            self.emergency_home()
            return False
        time.sleep(2)

        # ===== 紅蘿蔔：取料 → 送進切割區 → 切（切完就留在混拌區） =====
        self.out("【紅蘿蔔】")
        if not self.send_cmd("PICKUP,PICKUP_CARROT,F60_F,0,0,0"):
            self.emergency_home()
            return False
        time.sleep(2)

        if not self.send_cmd("PLACE,PICKUP_CARROT,WORK_CHOP_ZONE,SCOOP"):
            self.emergency_home()
            return False
        time.sleep(2)

        # 紅蘿蔔切完就留在原地 — 切割區跟混拌區是同一個座標，不需要再搬一次。
        # 小黃瓜要搬走是因為得把切割區讓給紅蘿蔔，紅蘿蔔是最後一個切的所以留著。
        if not self.send_cmd("CHOP,CARROT,15,5", timeout=420):
            self.emergency_home()
            return False
        time.sleep(2)

        # ===== 羅曼生菜：取料 → 直接進混拌區（不切，所以不經過切割區） =====
        self.out("【羅曼生菜】")
        if not self.send_cmd("PICKUP,PICKUP_ROMAINE,F60_F,0,0,0"):
            self.emergency_home()
            return False
        time.sleep(2)

        if not self.send_cmd("PLACE,PICKUP_ROMAINE,MIX_ZONE,SCOOP"):
            self.emergency_home()
            return False
        time.sleep(2)

        # ===== 取回小黃瓜：暫放區 → 混拌區 =====
        # AS 的 DO_PLACE 完全沒有使用 .$source 參數，只看 .$location，
        # 所以不能靠一句 PLACE 從暫放區搬到混拌區（會空手做一次放置動作）。
        # DO_PICKUP 有 WAIT_ZONE 分支，取回要照 PICKUP → PLACE 的兩段式。
        self.out("【取回小黃瓜】")
        if not self.send_cmd("PICKUP,WAIT_ZONE,F60_F,0,0,0"):
            self.emergency_home()
            return False
        time.sleep(2)

        if not self.send_cmd("PLACE,WAIT_ZONE,MIX_ZONE,SCOOP"):
            self.emergency_home()
            return False
        time.sleep(2)

        self.out("="*70)
        self.out("✓ 三種食材全數進入混拌區")
        self.out("="*70 + "\n")

        # ===== 翻炒 =====
        self.out("【翻炒】")
        self.log("⏳ 翻炒中... (6 循環，約 18 秒)")
        if not self.send_cmd("FLIP,6,50", timeout=300):
            self.emergency_home()
            return False
        time.sleep(2)

        self.out("="*70)
        self.out("✓ 翻炒完成")
        self.out("="*70 + "\n")

        # ===== 倒盤：夾起拌好的沙拉 → 倒進沙拉盤 =====
        # 跟 CHOP 完一樣，翻炒完沙拉是躺在混拌區的，要先 PICKUP 夾起來才能倒。
        self.out("【倒盤】")
        if not self.send_cmd("PICKUP,MIX_ZONE,F60_F,0,0,0"):
            self.emergency_home()
            return False
        time.sleep(2)

        if not self.send_cmd("PLACE,MIX_ZONE,SALAD_BOWL,POUR"):
            self.emergency_home()
            return False
        time.sleep(2)

        # ===== 復歸 =====（send_cmd 會自動各發各的 arm 名稱）
        self.out("【復歸】")
        if not self.send_cmd("HOME"):
            return False
        time.sleep(1)

        self.out("="*70)
        self.out("✓✓✓ 完整工作流程成功完成！✓✓✓")
        self.out("="*70)

        return True

    def emergency_home(self):
        """
        緊急復歸（失敗時使用）

        先送 STOP 再送 HOME：失敗通常是逾時，此時手臂多半還卡在 SYNC_STEP、
        robot_busy 仍是 1，AS 端 DISPATCH 會把 HOME 擋掉直接回 BUSY。只有
        STOP 在 busy 狀態下仍會被執行（BRAKE + robot_busy = 0）。
        """
        self.log("\n⚠️ 執行緊急復歸...")
        for cmd in ("STOP", "HOME"):
            for name, sock in (("F60_F", self.sock_f60f), ("F60_R", self.sock_f60r)):
                text = cmd if cmd == "STOP" else f"HOME,{name}"
                try:
                    sock.sendall((text + "\n").encode())
                    self.log(f"  {name} {text} → {self.recv_line(name, sock, 15)}")
                except Exception as e:
                    self.log(f"  {name} {text} → 失敗: {e}")
        self.log("⚠️ 緊急復歸結束，請目視確認兩臂位置")

    def close(self):
        """關閉連接與 log 檔"""
        if self.sock_f60f:
            self.sock_f60f.close()
        if self.sock_f60r:
            self.sock_f60r.close()
        if not self.log_file.closed:
            self.out(f"\n完整紀錄: {self.log_path}")
            self.log_file.close()


if __name__ == "__main__":
    controller = RobotController()

    try:
        if controller.run():
            controller.out("\n✓ 測試成功")
            sys.exit(0)
        else:
            controller.out("\n✗ 測試失敗")
            sys.exit(1)
    except KeyboardInterrupt:
        controller.out("\n⚠️ 用戶中斷")
        sys.exit(1)
    except Exception as e:
        import traceback
        controller.out(f"\n✗ 錯誤: {e}")
        controller.out(traceback.format_exc())
        sys.exit(1)
    finally:
        controller.close()
