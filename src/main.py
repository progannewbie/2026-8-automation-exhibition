"""
SmartCook 主程序 (Main Program)
菜單、主循環、系統協調
"""

import os
import sys
import json
import time
import logging
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from config_phase import MENU, get_recipe
from comms_connection_skeleton import CommsManager
from vision_skeleton import VisionSystem
from phase_controller_skeleton import PhaseController

# ============================================================================
# 全局配置
# ============================================================================

PROGRAM_NAME = "SmartCook"
PROGRAM_VERSION = "1.0.0"
PROGRAM_DATE = "2026/7/23"

LOG_DIR = "logs"
STATS_DIR = "stats"

RECONNECT_RETRIES = 3
RECONNECT_DELAY_SEC = 2.0

logger = logging.getLogger(__name__)


# ============================================================================
# 日誌設定
# ============================================================================

def _setup_logging() -> str:
    """設定日誌：同時輸出到檔案與終端機"""
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, datetime.now().strftime("smartcook_%Y%m%d_%H%M%S.log"))

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
# 程序狀態
# ============================================================================

class ProgramState(Enum):
    INIT = "INIT"
    READY = "READY"
    EXECUTING = "EXECUTING"
    ERROR = "ERROR"
    SHUTDOWN = "SHUTDOWN"


# ============================================================================
# 主應用
# ============================================================================

class SmartCookApp:
    """
    SmartCook 主程序

    職責：
    1. 初始化通訊、視覺、流程控制器
    2. 顯示菜單並處理用戶輸入
    3. 執行菜色並回報結果
    4. 處理異常與優雅關閉
    """

    def __init__(self):
        self.state = ProgramState.INIT

        self.comms: Optional[CommsManager] = None
        self.vision: Optional[VisionSystem] = None
        self.controller: Optional[PhaseController] = None

        self.session_date = datetime.now().strftime("%Y-%m-%d")
        self.session_start: Optional[float] = None

        self.statistics: Dict = {
            "total_recipes_run": 0,
            "successful_recipes": 0,
            "failed_recipes": 0,
            "total_runtime_sec": 0.0,
        }
        self.recipe_history: List[Dict] = []

    # ------------------------------------------------------------------
    # 初始化與生命週期
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """初始化所有系統：通訊 → 視覺 → 流程控制器"""
        logger.info(f"正在初始化 {PROGRAM_NAME} v{PROGRAM_VERSION} ...")

        try:
            self.comms = CommsManager()
            if not self.comms.connect_all():
                logger.error("✗ 機器人連線失敗，請檢查網線和 IP 設置")
                self.state = ProgramState.ERROR
                return False

            self.vision = VisionSystem()
            self.controller = PhaseController(self.vision, self.comms)

            self.session_start = time.time()
            self.state = ProgramState.READY
            logger.info("✓ 系統初始化完成，就緒")
            return True

        except Exception as exc:
            logger.error(f"✗ 初始化異常: {exc}", exc_info=True)
            self.state = ProgramState.ERROR
            return False

    def run(self) -> int:
        """運行主循環，回傳退出代碼"""
        self.print_welcome()

        if not self.initialize():
            print("\n✗ 系統初始化失敗，程序無法啟動。請檢查上方日誌訊息。")
            return 1

        try:
            while self.state != ProgramState.SHUTDOWN:
                self.display_menu()
                choice = input("輸入選擇 (1/2/3/4/q/?): ").strip().lower()
                self.process_user_input(choice)
        except KeyboardInterrupt:
            print("\n\n⚠️ 偵測到中斷 (Ctrl+C)，正在安全關閉...")
        except Exception as exc:
            self.handle_error(exc)
        finally:
            self.shutdown()

        return 0 if self.state != ProgramState.ERROR else 1

    def shutdown(self):
        """優雅關閉應用：機器人復歸、斷線、保存統計"""
        if self.state == ProgramState.SHUTDOWN:
            return

        logger.info("正在關閉系統...")

        if self.comms:
            for arm in ("F60_F", "F60_R"):
                try:
                    self.comms.send_command(arm, f"HOME,{arm}")
                except Exception as exc:
                    logger.warning(f"⚠️ {arm} 復歸失敗: {exc}")
            self.comms.disconnect_all()

        self._save_statistics()
        self.state = ProgramState.SHUTDOWN
        self.print_goodbye()

    # ------------------------------------------------------------------
    # 菜單交互
    # ------------------------------------------------------------------

    def display_menu(self):
        """顯示菜單"""
        status = self.get_status()

        print("\n" + "=" * 43)
        print(f"    {PROGRAM_NAME} 雙臂主廚機器人控制系統")
        print(f"             v{PROGRAM_VERSION} ({PROGRAM_DATE})")
        print("=" * 43)
        print()
        print(f"狀態: {'✓ 系統就緒' if status['ready'] else '✗ 系統異常'}")
        print(f"     - F60_F (左臂): {'已連接 ✓' if status['f60_f_connected'] else '未連接 ✗'}")
        print(f"     - F60_R (右臂): {'已連接 ✓' if status['f60_r_connected'] else '未連接 ✗'}")
        print(f"     - YOLO 模型: {'已載入 ✓' if status['vision_ready'] else '未載入 ✗'}")
        print()
        print("-" * 43)
        print("請選擇菜色 (輸入 1-4):\n")

        for choice in ("1", "2", "3", "4"):
            recipe = get_recipe(choice)
            warning = "\n     ⚠️ 連續執行模式 - 不能暫停！" if recipe.get("continuous") else ""
            print(f"  {choice}. {recipe['name']}")
            print(f"     {recipe['description']}")
            print(f"     ⏱️ 預估: ~{recipe['estimated_time_sec']} 秒{warning}\n")

        print("-" * 43)
        print("  q. 退出程序")
        print("  ? 幫助")
        print("-" * 43)

    def process_user_input(self, choice: str) -> bool:
        """處理用戶輸入"""
        if choice == "q":
            if self.confirm_action("確認退出程序?"):
                self.state = ProgramState.SHUTDOWN
            return True

        if choice == "?":
            self._display_help()
            return True

        recipe = get_recipe(choice)
        if recipe is None:
            print("✗ 輸入無效，請重新選擇")
            return False

        print(f"\n您選擇了: {recipe['name']}")
        print(f"預估時間: {recipe['estimated_time_sec']} 秒")
        if recipe.get("continuous"):
            print("⚠️ 注意: 此模式為連續執行，開始後不能中斷")

        if not self.confirm_action("確認開始?"):
            return True

        self.execute_recipe(choice)
        return True

    def confirm_action(self, message: str) -> bool:
        """確認對話"""
        answer = input(f"{message} (y/n): ").strip().lower()
        return answer == "y"

    def _display_help(self):
        """顯示幫助信息"""
        print("\n幫助 - 菜色說明")
        print("-" * 43)
        print("\n菜色 1-3 (單品菜色):")
        print("  • 可隨時暫停 (按 Ctrl+C)")
        print("  • 如果失敗，可重新選擇相同菜色重試")
        print("  • 機器人會自動重試 3 次")
        print("\n菜色 4 (完整沙拉流程) ⚠️:")
        print("  • 連續執行模式 - 開始後不能中斷！")
        print("  • 中間任何階段失敗 → 整個流程終止")
        print("  • 不建議中途按 Ctrl+C，應等待完成")
        print("  • 完成後自動回到 HOME 位置")
        print("\n技術信息:")
        print("  • TCP 連線埠: 9000")
        print("  • 視覺檢測精度: ±5mm")
        print("  • Hand-eye 標定精度: ±3mm")
        print("  • YOLO 信心度: ≥0.7")
        print("\n問題排查:")
        print("  • 機器人無反應 → 檢查網線和 IP 設置")
        print("  • 視覺檢測失敗 → 改善光線、重新拍照")
        print("  • 標定精度不足 → 重新執行 Hand-eye 標定")
        print("-" * 43)
        input("按 Enter 返回菜單...")

    # ------------------------------------------------------------------
    # 執行流程
    # ------------------------------------------------------------------

    def execute_recipe(self, choice: str) -> bool:
        """執行指定菜色"""
        self.state = ProgramState.EXECUTING

        if not self.controller.select_menu(choice):
            print(f"✗ 無效的菜色選擇: {choice}")
            self.state = ProgramState.READY
            return False

        start = time.time()
        try:
            success = self.controller.execute()
        except Exception as exc:
            self.handle_error(exc)
            success = False
        duration = time.time() - start

        self.controller.print_execution_report()
        self.handle_execution_complete(success, choice, duration)

        self.state = ProgramState.READY if self.state != ProgramState.ERROR else self.state
        input("按 Enter 返回菜單...")
        return success

    def handle_execution_complete(self, success: bool, choice: str, duration: float):
        """處理執行完成：更新統計與歷史紀錄"""
        recipe = get_recipe(choice) or {}

        self.statistics["total_recipes_run"] += 1
        self.statistics["total_runtime_sec"] += duration
        if success:
            self.statistics["successful_recipes"] += 1
        else:
            self.statistics["failed_recipes"] += 1

        self.recipe_history.append({
            "recipe": choice,
            "name": recipe.get("name", choice),
            "success": success,
            "duration_sec": round(duration, 1),
            "timestamp": datetime.now().isoformat(),
        })

    # ------------------------------------------------------------------
    # 異常處理
    # ------------------------------------------------------------------

    def handle_error(self, exception: Exception):
        """處理異常"""
        logger.error(f"✗ 系統錯誤: {exception}", exc_info=True)
        self.state = ProgramState.ERROR
        print(f"\n✗ 系統錯誤: {exception}")

        if not self.recover_from_error():
            print("✗ 無法恢復連接，請檢查網線連接，然後重新啟動程序")

    def recover_from_error(self) -> bool:
        """異常恢復：嘗試重建機器人連線"""
        if not self.comms:
            return False

        print("嘗試重新連接...")
        for attempt in range(1, RECONNECT_RETRIES + 1):
            if self.comms.connect_all():
                logger.info("✓ 重新連線成功")
                self.state = ProgramState.READY
                return True
            logger.warning(f"重新連線嘗試 {attempt}/{RECONNECT_RETRIES} 失敗")
            time.sleep(RECONNECT_DELAY_SEC)

        self.state = ProgramState.ERROR
        return False

    # ------------------------------------------------------------------
    # 狀態查詢
    # ------------------------------------------------------------------

    def get_status(self) -> Dict:
        """取得系統狀態"""
        f60_f_connected = bool(self.comms and self.comms.f60_f and self.comms.f60_f.is_connected())
        f60_r_connected = bool(self.comms and self.comms.f60_r and self.comms.f60_r.is_connected())
        vision_ready = bool(self.vision and self.vision.yolo_detector.model is not None)

        return {
            "ready": self.state == ProgramState.READY,
            "f60_f_connected": f60_f_connected,
            "f60_r_connected": f60_r_connected,
            "vision_ready": vision_ready,
        }

    def get_statistics(self) -> Dict:
        """取得統計信息"""
        return dict(self.statistics)

    # ------------------------------------------------------------------
    # 日誌與報告
    # ------------------------------------------------------------------

    def print_welcome(self):
        """顯示歡迎信息"""
        print("=" * 43)
        print(f"    {PROGRAM_NAME} 雙臂主廚機器人控制系統")
        print(f"             v{PROGRAM_VERSION} ({PROGRAM_DATE})")
        print("=" * 43)
        print("\n正在啟動系統，請稍候...\n")

    def print_goodbye(self):
        """顯示退出信息"""
        stats = self.get_statistics()
        print("\n" + "=" * 43)
        print("感謝使用 SmartCook！")
        print(f"本次執行: {stats['total_recipes_run']} 個菜色 "
              f"(成功 {stats['successful_recipes']} / 失敗 {stats['failed_recipes']})")
        print(f"總耗時: {stats['total_runtime_sec']:.1f} 秒")
        print("=" * 43)

    def _save_statistics(self):
        """保存本次統計到 stats/stats_YYYYMMDD.json"""
        os.makedirs(STATS_DIR, exist_ok=True)
        stats_path = os.path.join(STATS_DIR, f"stats_{self.session_date.replace('-', '')}.json")

        payload = {
            "date": self.session_date,
            "recipes_executed": self.statistics["total_recipes_run"],
            "recipes_successful": self.statistics["successful_recipes"],
            "recipes_failed": self.statistics["failed_recipes"],
            "total_runtime_sec": round(self.statistics["total_runtime_sec"], 1),
            "recipe_details": self.recipe_history,
        }

        try:
            with open(stats_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.info(f"✓ 統計已保存: {stats_path}")
        except OSError as exc:
            logger.warning(f"⚠️ 統計保存失敗: {exc}")


# ============================================================================
# 進入點
# ============================================================================

def main() -> int:
    _setup_logging()
    app = SmartCookApp()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
