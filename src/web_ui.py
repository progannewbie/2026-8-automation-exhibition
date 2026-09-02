#!/usr/bin/env python3
"""
SmartCook 展場觸控介面（Flask）

在控制電腦上跑起來，用瀏覽器全螢幕開 http://localhost:5000 當觸控畫面。
四個菜色對應 config_phase.MENU 的 1~4。

用法:
    python web_ui.py                # 連真的手臂
    python web_ui.py --simulate     # 不連手臂，純測介面（任何電腦都能跑）
    python web_ui.py --port 8080
    python web_ui.py --host 0.0.0.0 # 讓平板/手機連進來

⚠️ 「停止」鍵只能在階段與階段之間生效。單一階段送出去之後 PC 端是卡在
   recv() 等手臂回應，切割那種要 4 分鐘的階段按下去要等它跑完才會停。
   真正的緊急停止是實體急停按鈕，這顆按鈕不是安全裝置。
"""

import argparse
import logging
import os
import sys
import threading
import time
from datetime import datetime
from typing import Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, render_template, request

from config_phase import MENU, get_recipe, get_phases, Phase

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(_BASE_DIR, "logs")

logger = logging.getLogger(__name__)


def _setup_logging() -> str:
    """設定日誌：同時輸出到檔案與終端機"""
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, datetime.now().strftime("web_ui_%Y%m%d_%H%M%S.log"))

    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
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
    {"key": "3", "name": "生菜",     "icon": "🥬", "desc": "整片裝盤"},
    {"key": "4", "name": "生菜沙拉", "icon": "🥗", "desc": "三種食材，翻炒後裝盤"},
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
            from phase_controller_skeleton import PhaseController

            self.comms = CommsManager()
            if not self.comms.connect_all():
                self.init_error = "手臂連線失敗，請檢查網線與 IP 設定"
                logger.error(f"✗ {self.init_error}")
                return False

            # ⚠️ 視覺處理暫時停用，不載入 YOLO/ArUco/手眼標定，PICKUP 一律用教點座標。
            # 要恢復時把 import 跟下面這行取消註解、拿掉 self.vision = None。
            # from vision_skeleton import VisionSystem
            # self.vision = VisionSystem()
            self.vision = None
            self.controller = PhaseController(self.vision, self.comms)
            self.ready = True
            logger.info("✓ 系統就緒")
            return True

        except Exception as exc:
            self.init_error = f"初始化異常: {exc}"
            logger.error(f"✗ {self.init_error}", exc_info=True)
            return False

    # ---------------------------------------------------------------- 執行

    def _begin(self, title: str, steps_text: list, phases: list) -> None:
        """共用的開跑前置。呼叫端必須已持有 self.lock。"""
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
            self._begin(task["name"], [f"{task['name']}中…"], [None])

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
                    self.error = "流程中斷，請看 log 確認失敗的階段"
        except Exception as exc:
            logger.error(f"✗ 執行異常: {exc}", exc_info=True)
            self.error = str(exc)
            success = False

        self._finish(success)

    def _run_task(self, task: Dict):
        cmd = task["cmd"]
        logger.info(f"=== 開始執行 {task['name']}（{cmd}）===")
        try:
            if self.simulate:
                time.sleep(4.0)
                success = not self.stopping
            else:
                resp = self.comms.send_command_dual(cmd)
                logger.info(f"  F60_F={resp.get('F60_F')}  F60_R={resp.get('F60_R')}")
                success = resp.get("F60_F") == "OK" and resp.get("F60_R") == "OK"
                if not success:
                    self.error = (f"F60_F={resp.get('F60_F')}, F60_R={resp.get('F60_R')}"
                                  f"（{cmd} 需要兩臂 AS 都有對應的 DISPATCH 分支並回 OK）")
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
                "error": self.error,
            }


# ============================================================================
# Flask
# ============================================================================

def create_app(runner: RobotRunner) -> Flask:
    app = Flask(__name__)

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
        return render_template("index.html", dishes=dishes, tasks=tasks,
                               simulate=runner.simulate)

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
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--simulate", action="store_true", help="不連手臂，純測介面")
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 可讓平板連進來")
    ap.add_argument("--port", type=int, default=5000)
    args = ap.parse_args()

    log_path = _setup_logging()
    logger.info(f"日誌檔案: {log_path}")

    runner = RobotRunner(simulate=args.simulate)
    if not runner.initialize():
        print(f"\n✗ {runner.init_error}")
        print("  介面仍會啟動，但菜色會是停用狀態。")
        print("  想先看介面長什麼樣，改用: python web_ui.py --simulate\n")

    app = create_app(runner)
    print("\n" + "=" * 60)
    print(f"  觸控介面: http://{'localhost' if args.host=='127.0.0.1' else args.host}:{args.port}")
    if args.simulate:
        print("  ⚠️ 模擬模式，不會真的驅動手臂")
    print("  瀏覽器按 F11 全螢幕。Ctrl+C 結束。")
    print("=" * 60 + "\n")

    app.run(host=args.host, port=args.port, threaded=True, debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
