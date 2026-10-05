#!/usr/bin/env python3
"""
SmartCook 展場觸控介面（Flask）

在控制電腦上跑起來，用瀏覽器全螢幕開 http://localhost:5000 當觸控畫面。
四個菜色對應 config_phase.MENU 的 1~4。

用法:
    python web_ui.py                # 連真的手臂
    python web_ui.py --simulate     # 不連手臂，純測介面（任何電腦都能跑）
    python web_ui.py --port 8080
    python web_ui.py --host 0.0.0.0 # 讓平板/手機連進來（會自動產生存取金鑰）
    python web_ui.py --host 0.0.0.0 --token 自訂金鑰

⚠️ 開放 --host 給其他裝置時，同網段任何人都能驅動手臂，所以一律要求金鑰：
   第一次用終端機印出的 http://…/?key=… 網址開啟，之後瀏覽器會記住。

⚠️ 「停止」鍵只能在階段與階段之間生效。單一階段送出去之後 PC 端是卡在
   recv() 等手臂回應，切割那種約 30 秒的階段按下去要等它跑完才會停。
   真正的緊急停止是實體急停按鈕，這顆按鈕不是安全裝置。
"""

import argparse
import hmac
import logging
import os
import secrets
import sys
import threading
import time
from datetime import datetime
from typing import Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, make_response, render_template, request

from config_phase import MENU, get_recipe, get_phases, Phase

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(_BASE_DIR, "logs")

logger = logging.getLogger(__name__)


def _setup_logging() -> str:
    """設定日誌：同時輸出到檔案與終端機"""
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, datetime.now().strftime("web_ui_%Y%m%d_%H%M%S.log"))

    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")

    # handler 也設 INFO：comms 模組自己開到 DEBUG（每拍心跳都記），那些只寫 connection.log
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    root_logger = logging.getLogger()
    # vision / phase_controller 為了單獨跑測試腳本時有輸出，import 時會 basicConfig
    # 掛一個 root handler；這裡由入口程式接手，先拿掉，不然終端機每行印兩次
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    return log_path

# ============================================================================
# 菜單顯示資料
# ============================================================================

# key 對應 config_phase.MENU
DISHES = [
    {"key": "1", "name": "小黃瓜",   "icon": "🥒", "desc": "切片裝盤"},
    {"key": "2", "name": "紅蘿蔔",   "icon": "🥕", "desc": "切片裝盤"},
    {"key": "3", "name": "生菜",     "icon": "🥬", "desc": "中間切一刀裝盤"},
    {"key": "4", "name": "生菜沙拉", "icon": "🥗", "desc": "三種食材依序切好裝盤"},
]

# 維護用動作：不是菜色，直接送一句 CSV 指令給兩臂，不走 PhaseController。
# cmd 要跟兩臂 AS 的 DISPATCH 裡的 SVALUE 字串完全一致。
TASKS = {
    "clean": {
        "name": "清理檯面",
        "icon": "🧹",
        "cmd": "DO_CLEAN",
        "desc": "把檯面上的殘料清乾淨",
        "notice": "請確認檯面上沒有餐具或雜物，<br>並確認機台周圍淨空。",
        "minutes": 1,
    },
}


def describe_phase(phase_instr) -> str:
    """把 PhaseInstruction 轉成觀眾看得懂的一句話"""
    action, loc = phase_instr.action, phase_instr.location
    params = phase_instr.params or {}

    if action == "PICKUP":
        return {
            "PICKUP_CUCUMBER": "夾起小黃瓜",
            "PICKUP_CARROT":   "夾起紅蘿蔔",
            "PICKUP_ROMAINE":  "夾起生菜",
            "MIX_ZONE":        "夾起切好的食材",
            "MIX_ZONE2":       "補撈剩下的食材",
            "WAIT_ZONE":       "取回暫存的食材",
        }.get(loc, f"夾取 {loc}")

    if action == "PLACE":
        return {
            "WORK_CHOP_ZONE": "送進切割區",
            "WAIT_ZONE_1":    "放到暫存區",
            "MIX_ZONE":       "放入混拌區",
            "SALAD_BOWL":     "裝盤",
        }.get(loc, f"放到 {loc}")

    if action == "CHOP":
        food = {"CUCUMBER": "小黃瓜", "CARROT": "紅蘿蔔", "ROMAINE": "生菜"}.get(
            params.get("food_type", ""), "食材")
        return f"切{food}（{params.get('num_cuts', '?')} 刀）"

    if action == "FLIP":
        return f"翻炒（{params.get('num_cycles', '?')} 循環）"

    if action == "MEASURE":
        food = {"CUCUMBER": "小黃瓜", "CARROT": "紅蘿蔔"}.get(params.get("food_type", ""), "食材")
        return f"量測{food}長度"

    if action == "HOME":
        return "手臂復歸"

    return action


# ============================================================================
# 機器人控制（背景執行緒）
# ============================================================================

class RobotRunner:
    """
    把 PhaseController 包成「一次跑一道菜」的背景工作

    狀態機:
        idle → running → done / failed → (reset) → idle
    """

    def __init__(self, simulate: bool = False):
        self.simulate = simulate
        self.lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None

        self.state = "idle"          # idle / running / done / failed
        self.choice: Optional[str] = None
        self.recipe_name = ""
        self.phases = []
        # 每一步要顯示給觀眾看的文字。菜色從 phases 展開，維護動作只有一步。
        self.steps_text: list = []
        self.started_at = 0.0
        self.finished_at = 0.0
        self.error = ""
        self.stopping = False
        self.stoppable = True

        self.comms = None
        self.vision = None
        self.controller = None
        self.ready = False
        self.init_error = ""

    # ---------------------------------------------------------------- 初始化

    def initialize(self) -> bool:
        """連線手臂、載入視覺。模擬模式直接跳過。"""
        if self.simulate:
            self.ready = True
            logger.info("✓ 模擬模式，未連線手臂")
            return True

        try:
            from comms_connection_skeleton import CommsManager
            from vision_skeleton import VisionSystem
            from phase_controller_skeleton import PhaseController

            self.comms = CommsManager()
            if not self.comms.connect_all():
                self.init_error = "手臂連線失敗，請檢查網線與 IP 設定"
                logger.error(f"✗ {self.init_error}")
                return False

            self.vision = VisionSystem()
            self.controller = PhaseController(self.vision, self.comms)
            self.ready = True
            logger.info("✓ 系統就緒")
            return True

        except Exception as exc:
            self.init_error = f"初始化異常: {exc}"
            logger.error(f"✗ {self.init_error}", exc_info=True)
            return False

    # ---------------------------------------------------------------- 執行

    def _begin(self, title: str, steps_text: list, phases: list,
               stoppable: bool = True) -> None:
        """共用的開跑前置。呼叫端必須已持有 self.lock。"""
        self.stoppable = stoppable
        self.recipe_name = title
        self.phases = phases
        self.steps_text = steps_text
        self.state = "running"
        self.started_at = time.time()
        self.finished_at = 0.0
        self.error = ""
        self.stopping = False
        self._sim_index = 0

    def _guard(self, ) -> Optional[Dict]:
        """共用的前置檢查，通過回 None"""
        if self.state == "running":
            return {"ok": False, "msg": "目前正在執行中"}
        if not self.ready:
            return {"ok": False, "msg": self.init_error or "系統尚未就緒"}
        return None

    def start(self, choice: str) -> Dict:
        """開始執行一道菜。已經在跑就拒絕。"""
        with self.lock:
            bad = self._guard()
            if bad:
                return bad
            if choice not in MENU:
                return {"ok": False, "msg": f"沒有這道菜: {choice}"}

            recipe = get_recipe(choice)
            phases = get_phases(choice)
            self.choice = choice
            self._begin(recipe["name"], [describe_phase(p) for p in phases], phases)

            self.thread = threading.Thread(target=self._run, args=(choice,), daemon=True)
            self.thread.start()
            return {"ok": True}

    def start_task(self, key: str) -> Dict:
        """
        開始執行維護動作（例如清理檯面）

        不走 PhaseController，直接把一句 CSV 指令同時送給兩臂並等兩邊都回 OK。
        """
        with self.lock:
            bad = self._guard()
            if bad:
                return bad
            task = TASKS.get(key)
            if not task:
                return {"ok": False, "msg": f"沒有這個動作: {key}"}

            self.choice = None
            # 維護動作是一句指令送出去就等到底，中間沒有階段邊界可以停
            self._begin(task["name"], [f"{task['name']}中…"], [None], stoppable=False)

            self.thread = threading.Thread(target=self._run_task, args=(task,), daemon=True)
            self.thread.start()
            return {"ok": True}

    def _run(self, choice: str):
        logger.info(f"=== 開始執行 {self.recipe_name} ===")
        try:
            if self.simulate:
                success = self._run_simulated()
            else:
                success = (self.controller.select_menu(choice)
                           and self.controller.execute())
                if not success and not self.error:
                    self.error = self._describe_failure()
        except Exception as exc:
            logger.error(f"✗ 執行異常: {exc}", exc_info=True)
            self.error = str(exc)
            success = False

        if not success and self.controller and self.controller.arms_off_home:
            self._lock_out(f"上次在「{self._current_step_text()}」中斷，手臂沒有復歸。"
                           f"請確認現場，用教導器把手臂移回原點")

        self._finish(success)

    def _current_step_text(self) -> str:
        idx = self.controller.current_phase_index if self.controller else 0
        return self.steps_text[idx] if 0 <= idx < len(self.steps_text) else ""

    def _describe_failure(self) -> str:
        """把 PhaseController 的失敗原因轉成給現場人員看的一句話"""
        detail = self.controller.failure_message if self.controller else ""
        if self.controller and self.controller.arms_off_home:
            return (f"在「{self._current_step_text()}」這步失敗，手臂停在原處、沒有自動復歸。"
                    f"（{detail}）")
        return detail or "流程中斷，請看 log 確認失敗的階段"

    def _lock_out(self, reason: str):
        """
        停用菜單，直到重新啟動程式

        手臂停在未知位置或連線已停用時，再按一道菜會從那個位置直接開跑，
        所以一律鎖住，要操作人員處理完現場再重開。
        """
        with self.lock:
            self.ready = False
            self.init_error = reason
        logger.error(f"✗ 菜單已停用: {reason}")

    def _run_task(self, task: Dict):
        cmd = task["cmd"]
        logger.info(f"=== 開始執行 {task['name']}（{cmd}）===")
        try:
            if self.simulate:
                time.sleep(4.0)
                success = True
            else:
                resp = self.comms.send_command_dual(cmd)
                logger.info(f"  F60_F={resp.get('F60_F')}  F60_R={resp.get('F60_R')}")
                success = resp.get("F60_F") == "OK" and resp.get("F60_R") == "OK"
                if not success:
                    self.error = (f"F60_F={resp.get('F60_F')}, F60_R={resp.get('F60_R')}"
                                  f"（{cmd} 需要兩臂 AS 都有對應的 DISPATCH 分支並回 OK）")
                    # 維護動作也是實體動作，失敗時手臂一樣可能停在半路
                    self._lock_out(f"「{task['name']}」沒有完成，手臂可能不在原點。"
                                   f"請確認現場，用教導器把手臂移回原點")
        except Exception as exc:
            logger.error(f"✗ {task['name']} 異常: {exc}", exc_info=True)
            self.error = str(exc)
            success = False

        self._finish(success)

    def _finish(self, success: bool):
        with self.lock:
            self.finished_at = time.time()
            if self.stopping:
                self.state = "failed"
                self.error = self.error or "已由操作人員停止"
            else:
                self.state = "done" if success else "failed"
        logger.info(f"=== {self.recipe_name} {'完成' if success else '結束（未完成）'} ===")

    def _run_simulated(self) -> bool:
        """模擬模式：每個階段停幾秒，讓介面能完整走一遍"""
        for i, _ in enumerate(self.phases):
            if self.stopping:
                return False
            self._sim_index = i
            time.sleep(2.0)
        self._sim_index = len(self.phases)
        return True

    def stop(self) -> Dict:
        with self.lock:
            if self.state != "running":
                return {"ok": False, "msg": "目前沒有在執行"}
            if not self.stoppable:
                return {"ok": False,
                        "msg": f"{self.recipe_name}無法中途停止，緊急狀況請按實體急停按鈕"}
            self.stopping = True

        if self.controller:
            self.controller.request_cancel()
        logger.warning("⚠️ 使用者按下停止")
        return {"ok": True, "msg": "會在目前動作結束後停止"}

    def reset(self) -> Dict:
        """從 done/failed 回到 idle，讓畫面回菜單"""
        with self.lock:
            if self.state == "running":
                return {"ok": False, "msg": "執行中無法重置"}
            self.state = "idle"
            self.error = ""
            return {"ok": True}

    # ---------------------------------------------------------------- 狀態

    def status(self) -> Dict:
        with self.lock:
            state, total = self.state, len(self.steps_text)

            # 閒置時順便檢查連線：心跳失敗或指令逾時都會把連線標成 ERROR，
            # 這裡要讓菜單跟著停用，不然觀眾按下去才在 STATUS 那步失敗。
            if state != "running" and self.ready and self.comms:
                broken = self.comms.broken_arms()
                if broken:
                    self.ready = False
                    self.init_error = f"與 {'、'.join(broken)} 的連線中斷，請檢查網線與手臂控制器"
                    logger.error(f"✗ {self.init_error}")

            if state == "running":
                # 維護動作只有一步、不經過 PhaseController，索引固定 0
                if self.choice is None or self.simulate:
                    idx = getattr(self, "_sim_index", 0)
                else:
                    idx = self.controller.current_phase_index
                idx = max(0, min(idx, total - 1)) if total else 0
                step_text = self.steps_text[idx] if total else ""
                elapsed = time.time() - self.started_at
            else:
                idx = total
                step_text = ""
                elapsed = (self.finished_at - self.started_at) if self.started_at else 0

            return {
                "state": state,
                "ready": self.ready,
                "init_error": self.init_error,
                "simulate": self.simulate,
                "recipe_name": self.recipe_name,
                "step": idx + 1 if state == "running" else total,
                "total": total,
                "percent": round((idx / total) * 100) if total and state == "running" else (
                    100 if state == "done" else 0),
                "step_text": step_text,
                "elapsed": round(elapsed),
                "stopping": self.stopping,
                "stoppable": self.stoppable,
                "error": self.error,
            }


# ============================================================================
# Flask
# ============================================================================

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
TOKEN_COOKIE = "smartcook_key"


def token_ok(token: Optional[str], supplied: Optional[str]) -> bool:
    """沒設金鑰一律放行；有設就要完全相符（用 compare_digest 避免逐字元比對的時間差）"""
    if not token:
        return True
    return bool(supplied) and hmac.compare_digest(supplied, token)


def create_app(runner: RobotRunner, token: Optional[str] = None) -> Flask:
    """
    Args:
        token: 存取金鑰。None 表示不檢查（只綁 127.0.0.1 時）。有設的話，
               第一次要用 /?key=<token> 開啟，之後靠 cookie 通過。
    """
    app = Flask(__name__)

    @app.before_request
    def _require_token():
        if token_ok(token, request.cookies.get(TOKEN_COOKIE)):
            return None
        if request.endpoint == "index" and token_ok(token, request.args.get("key")):
            return None   # index() 會順便把 cookie 種下去
        return ("需要存取金鑰：請用控制電腦終端機上印出的網址（含 ?key=…）開啟", 403)

    @app.route("/")
    def index():
        dishes = []
        for d in DISHES:
            recipe = get_recipe(d["key"]) or {}
            secs = recipe.get("estimated_time_sec", 0)
            dishes.append({**d,
                           "steps": len(get_phases(d["key"]) or []),
                           "minutes": max(1, round(secs / 60))})
        tasks = [{**v, "key": k} for k, v in TASKS.items()]
        resp = make_response(render_template("index.html", dishes=dishes, tasks=tasks,
                                             simulate=runner.simulate))
        if token and token_ok(token, request.args.get("key")):
            resp.set_cookie(TOKEN_COOKIE, token, max_age=60 * 60 * 24 * 30,
                            httponly=True, samesite="Strict")
        return resp

    @app.route("/api/status")
    def api_status():
        return jsonify(runner.status())

    @app.route("/api/start", methods=["POST"])
    def api_start():
        body = request.json or {}
        if body.get("task"):
            return jsonify(runner.start_task(body["task"]))
        return jsonify(runner.start(body.get("choice", "")))

    @app.route("/api/stop", methods=["POST"])
    def api_stop():
        return jsonify(runner.stop())

    @app.route("/api/reset", methods=["POST"])
    def api_reset():
        return jsonify(runner.reset())

    return app


def main() -> int:
    # 輸出被導向（捷徑、排程、別的程式啟動）時 stdout 會變成 cp950，
    # 印到 ⚠️ 這類字元就 UnicodeEncodeError 整個掛掉。改成印不出來的字元用跳脫碼代替。
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--simulate", action="store_true", help="不連手臂，純測介面")
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 可讓平板連進來")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--token", default=None,
                    help="存取金鑰。--host 不是本機時沒給就自動產生一組")
    args = ap.parse_args()

    # 開放給其他裝置時一定要有金鑰，否則同網段任何人都能驅動手臂
    token = args.token
    if not token and args.host not in LOOPBACK_HOSTS:
        token = secrets.token_urlsafe(6)

    log_path = _setup_logging()
    logger.info(f"日誌檔案: {log_path}")

    runner = RobotRunner(simulate=args.simulate)
    if not runner.initialize():
        print(f"\n✗ {runner.init_error}")
        print("  介面仍會啟動，但菜色會是停用狀態。")
        print("  想先看介面長什麼樣，改用: python web_ui.py --simulate\n")

    app = create_app(runner, token)
    url = f"http://{'localhost' if args.host=='127.0.0.1' else args.host}:{args.port}"
    print("\n" + "=" * 60)
    if token:
        # 金鑰只印在終端機，不寫進 log 檔
        print(f"  觸控介面: {url}/?key={token}")
        print("  ⚠️ 需要金鑰：每台平板第一次請用上面這個完整網址開啟")
        if args.host == "0.0.0.0":
            print("     （0.0.0.0 請換成控制電腦的 IP，例如 192.168.5.100）")
    else:
        print(f"  觸控介面: {url}")
    if args.simulate:
        print("  ⚠️ 模擬模式，不會真的驅動手臂")
    print("  瀏覽器按 F11 全螢幕。Ctrl+C 結束。")
    print("=" * 60 + "\n")

    app.run(host=args.host, port=args.port, threaded=True, debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
