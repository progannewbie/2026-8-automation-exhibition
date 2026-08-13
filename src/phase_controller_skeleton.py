"""
SmartCook 流程控制器 (Phase Controller)
管理菜色執行流程、狀態機、錯誤處理
"""

import time
import logging
from typing import Dict, List, Optional, Tuple
from enum import Enum

from config_phase import (
    Phase, PhaseStatus, PhaseInstruction, PhaseLog, RetryPolicy, MENU,
    get_recipe, get_phases, FOOD_CUT_PARAMS
)
from config_commands import (
    CommandParser, PickupCommand, ChopCommand, PlaceCommand,
    FlipCommand, HomeCommand, StatusCommand,
)
from vision_skeleton import VisionSystem
from comms_connection_skeleton import CommsManager

# ============================================================================
# 日誌設定
# ============================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# 流程控制器
# ============================================================================

class PhaseController:
    """
    流程控制器 - 管理整個菜色執行
    
    職責：
    1. 解析菜色（1/2/3/4）
    2. 執行階段序列
    3. 與視覺系統、通訊管理器集成
    4. 錯誤重試與異常處理
    5. 記錄執行日誌
    """
    
    def __init__(
        self,
        vision_system: VisionSystem,
        comms_manager: CommsManager
    ):
        """
        初始化流程控制器
        
        Args:
            vision_system: 視覺系統實例
            comms_manager: 通訊管理器實例
        """
        self.vision = vision_system
        self.comms = comms_manager
        
        self.current_recipe = None       # 當前食譜
        self.current_phase_index = 0     # 當前階段索引
        self.phases = []                 # 階段序列
        
        self.phase_logs = []             # 執行日誌
        self.start_time = None           # 開始時間
        self.end_time = None             # 結束時間
        
        self.is_continuous = False       # 是否連續執行
        self.total_estimated_time = 0    # 預估總時間

        # 停止要求。execute() 每跑完一個階段會檢查一次。
        # ⚠️ 只能在「階段與階段之間」生效——單一階段送出去之後，PC 端是卡在
        #    recv() 等手臂回應，而 send_command 的 socket_lock 也被佔著，
        #    沒辦法插隊送 STOP。切割那種要 4 分鐘的階段，按下去要等它跑完。
        #    真正的緊急停止是實體急停按鈕，這個旗標不能當安全裝置用。
        self.cancel_requested = False

        logger.info("✓ PhaseController 已初始化")

    def request_cancel(self):
        """要求在目前階段結束後停止（非緊急停止，見 cancel_requested 說明）"""
        self.cancel_requested = True
        logger.warning("⚠️ 收到停止要求，會在目前階段結束後中止")
    
    # ========================================================================
    # 菜色選擇與初始化
    # ========================================================================
    
    def select_menu(self, choice: str) -> bool:
        """
        選擇菜色
        
        Args:
            choice: "1", "2", "3", "4"
        
        Returns:
            True 成功，False 無效選擇
        """
        recipe = get_recipe(choice)
        
        if recipe is None:
            logger.error(f"✗ 無效的菜色選擇: {choice}")
            return False
        
        self.current_recipe = recipe
        self.phases = recipe.get("phases", [])
        self.is_continuous = recipe.get("continuous", False)
        self.total_estimated_time = recipe.get("estimated_time_sec", 0)
        self.current_phase_index = 0
        self.phase_logs = []
        
        logger.info(f"✓ 已選擇: {recipe['name']}")
        logger.info(f"  描述: {recipe['description']}")
        logger.info(f"  預估時間: {self.total_estimated_time} 秒")
        
        if self.is_continuous:
            logger.warning("  ⚠️ 連續執行模式 - 不能中斷！")
        
        return True
    
    # ========================================================================
    # 主執行流程
    # ========================================================================
    
    def execute(self) -> bool:
        """
        執行整個菜色流程
        
        Returns:
            True 成功，False 失敗
        """
        if not self.current_recipe:
            logger.error("✗ 未選擇菜色")
            return False
        
        self.start_time = time.time()
        self.cancel_requested = False
        logger.info(f"\n{'='*60}")
        logger.info(f"開始執行: {self.current_recipe['name']}")
        logger.info(f"{'='*60}\n")

        try:
            # 初始化手臂
            if not self._initialize_arms():
                logger.error("✗ 手臂初始化失敗")
                return False

            # 執行各階段
            for i, phase_instr in enumerate(self.phases):
                if self.cancel_requested:
                    logger.warning(f"⚠️ 使用者要求停止，在第 {i+1} 階段前中止")
                    self._handle_home("HOME_LEFT", {}, 1)
                    return False

                self.current_phase_index = i

                logger.info(f"\n[{i+1}/{len(self.phases)}] 階段: {phase_instr.phase.value}")

                if not self._execute_phase(phase_instr):
                    logger.error(f"✗ 階段執行失敗: {phase_instr.phase.value}")
                    
                    if self.is_continuous:
                        logger.error("✗ 連續執行模式，無法恢復")
                        return False
                    else:
                        logger.warning("⚠️ 可嘗試重試或重新開始")
                        return False
            
            # 完成
            self.end_time = time.time()
            duration = self.end_time - self.start_time
            
            logger.info(f"\n{'='*60}")
            logger.info(f"✓ 菜色完成！")
            logger.info(f"  總耗時: {duration:.1f} 秒")
            logger.info(f"  預估時間: {self.total_estimated_time} 秒")
            logger.info(f"{'='*60}\n")
            
            return True
            
        except Exception as e:
            logger.error(f"✗ 執行異常: {e}")
            return False
    
    # ========================================================================
    # 單階段執行
    # ========================================================================
    
    def _execute_phase(self, phase_instr: PhaseInstruction) -> bool:
        """
        執行單個階段
        
        Args:
            phase_instr: 階段指令
        
        Returns:
            True 成功，False 失敗
        """
        phase = phase_instr.phase
        action = phase_instr.action
        location = phase_instr.location
        params = phase_instr.params or {}
        
        # 記錄開始
        log = PhaseLog(
            phase=phase,
            status=PhaseStatus.RUNNING,
            start_time=time.time(),
            end_time=None,
            duration_sec=None,
            error_msg=None,
            retry_count=0,
        )
        
        # 執行邏輯
        success = False
        
        if action == "PICKUP":
            success = self._handle_pickup(location, params, phase_instr.retries)
        elif action == "CHOP":
            success = self._handle_chop(location, params, phase_instr.retries)
        elif action == "PLACE":
            success = self._handle_place(location, params, phase_instr.retries)
        elif action == "FLIP":
            success = self._handle_flip(location, params, phase_instr.retries)
        elif action == "HOME":
            success = self._handle_home(location, params, phase_instr.retries)
        else:
            logger.error(f"✗ 未知的動作: {action}")
            log.status = PhaseStatus.FAILED
            log.error_msg = f"Unknown action: {action}"
        
        # 更新日誌
        log.end_time = time.time()
        log.duration_sec = log.end_time - log.start_time
        log.status = PhaseStatus.SUCCESS if success else PhaseStatus.FAILED
        
        self.phase_logs.append(log)
        
        return success
    
    # ========================================================================
    # 指令驗證
    # ========================================================================

    def _validate_command(self, cmd: str, validator) -> bool:
        """
        送出前用 CommandParser 驗證指令格式

        Args:
            cmd: CSV 格式指令字串
            validator: CommandParser 的 validate_* 靜態方法

        Returns:
            True 格式正確，False 格式錯誤（不應送出）
        """
        _, cmd_params = CommandParser.parse(cmd)
        if not validator(cmd_params):
            logger.error(f"  ✗ 指令格式驗證失敗，不送出: {cmd}")
            return False
        return True

    # ========================================================================
    # 具體動作實現
    # ========================================================================

    def _handle_pickup(self, location: str, params: Dict, max_retries: int) -> bool:
        """處理取料"""
        arm = params.get("arm", "F60_F")

        # PICKUP_<食材> 這幾個點位改用 YOLO + 手眼標定即時算座標；
        # WAIT_ZONE 這類暫存區沒有視覺目標，維持送 0,0,0（AS 端會忽略，用教點）
        expected_food = location if location in PickupCommand.VISION_LOCATIONS else None
        expected_food = expected_food[len("PICKUP_"):] if expected_food else None

        for attempt in range(max_retries):
            try:
                x_mm, y_mm, angle_deg = 0.0, 0.0, 0.0

                if expected_food:
                    image = self.vision.capture_frame()
                    detection = (
                        self.vision.get_location_and_angle_mm(expected_food, image)
                        if image is not None else None
                    )
                    if detection is None:
                        logger.warning(f"  ⚠️ 視覺未偵測到 {expected_food}，中止本次取料，不送指令給機器人")
                        if attempt < max_retries - 1:
                            time.sleep(RetryPolicy.RETRY_DELAY_SEC)
                        continue
                    x_mm, y_mm, angle_deg = detection
                    logger.info(f"  視覺定位 {expected_food}: x={x_mm:.1f}mm, y={y_mm:.1f}mm, angle={angle_deg:.1f}°")

                cmd = PickupCommand.create(location, arm, x_mm, y_mm, angle_deg)
                if not self._validate_command(cmd, CommandParser.validate_pickup):
                    return False

                logger.info(f"  取料: {location} (雙臂協同)")

                # 各臂的 AS DO_PICKUP 都會檢查 arm 欄位是不是自己
                # （左臂要 "F60_F"、右臂要 "F60_R"），不符就回 ERROR,E4003。
                # 送同一個字串給兩邊必定有一邊被拒，所以各自帶自己的名稱。
                cmds = {
                    a: PickupCommand.create(location, a, x_mm, y_mm, angle_deg)
                    for a in ("F60_F", "F60_R")
                }
                # PICKUP 兩臂會逐階段用 SYNC_STEP 會合，指令必須同時送給兩邊
                responses = self.comms.send_command_dual(cmds)
                if responses.get("F60_F") == "OK" and responses.get("F60_R") == "OK":
                    logger.info(f"  ✓ 取料成功")
                    return True
                else:
                    logger.warning(f"  ⚠️ 取料回應異常: F60_F={responses.get('F60_F')}, F60_R={responses.get('F60_R')}")

            except Exception as e:
                logger.warning(f"  ⚠️ 取料嘗試 {attempt+1}/{max_retries} 失敗: {e}")

            if attempt < max_retries - 1:
                time.sleep(RetryPolicy.RETRY_DELAY_SEC)

        logger.error(f"  ✗ 取料失敗 (重試 {max_retries} 次)")
        return False
    
    def _handle_chop(self, location: str, params: Dict, max_retries: int) -> bool:
        """處理切割"""
        food_type = params.get("food_type", "CUCUMBER")
        num_cuts = params.get("num_cuts", 5)
        thickness = params.get("cut_thickness_mm", 4.0)
        cmd = ChopCommand.create(food_type, num_cuts, thickness)

        if not self._validate_command(cmd, CommandParser.validate_chop):
            return False

        for attempt in range(max_retries):
            try:
                logger.info(f"  切割: {food_type} ({num_cuts} 次，{thickness} mm，雙臂協同)")

                # CHOP 兩臂逐刀用 SYNC_STEP 會合 (F60_F 切、F60_R 壓料步進)，指令必須同時送給兩邊
                responses = self.comms.send_command_dual(cmd)
                if responses.get("F60_F") == "OK" and responses.get("F60_R") == "OK":
                    logger.info(f"  ✓ 切割完成")
                    return True
                else:
                    logger.warning(f"  ⚠️ 切割回應異常: F60_F={responses.get('F60_F')}, F60_R={responses.get('F60_R')}")
                    
            except Exception as e:
                logger.warning(f"  ⚠️ 切割嘗試 {attempt+1}/{max_retries} 失敗: {e}")
            
            if attempt < max_retries - 1:
                time.sleep(RetryPolicy.RETRY_DELAY_SEC)
        
        logger.error(f"  ✗ 切割失敗 (重試 {max_retries} 次)")
        return False
    
    def _handle_place(self, location: str, params: Dict, max_retries: int) -> bool:
        """處理放置"""
        source = params.get("source", "WORK_CHOP_ZONE")
        method = params.get("method", "SCOOP")
        cmd = PlaceCommand.create(source, location, method)

        if not self._validate_command(cmd, CommandParser.validate_place):
            return False

        # 一律雙臂。食材是夾在兩支鏟子中間搬運的，只送左臂的話右臂不動，
        # 東西會掉。兩臂的 AS DO_PLACE 都有完整的目的地分支（WAIT_ZONE_1 /
        # MIX_ZONE / SALAD_BOWL / WORK_CHOP_ZONE），SCOOP/PUSH/POUR 都收。
        for attempt in range(max_retries):
            try:
                logger.info(f"  放置: {source} → {location} (方式: {method}，雙臂協同)")

                responses = self.comms.send_command_dual(cmd)
                ok = responses.get("F60_F") == "OK" and responses.get("F60_R") == "OK"
                response_desc = f"F60_F={responses.get('F60_F')}, F60_R={responses.get('F60_R')}"

                if ok:
                    logger.info(f"  ✓ 放置完成")
                    return True
                else:
                    logger.warning(f"  ⚠️ 放置回應異常: {response_desc}")
                    
            except Exception as e:
                logger.warning(f"  ⚠️ 放置嘗試 {attempt+1}/{max_retries} 失敗: {e}")
            
            if attempt < max_retries - 1:
                time.sleep(RetryPolicy.RETRY_DELAY_SEC)
        
        logger.error(f"  ✗ 放置失敗 (重試 {max_retries} 次)")
        return False
    
    def _handle_flip(self, location: str, params: Dict, max_retries: int) -> bool:
        """處理翻炒"""
        num_cycles = params.get("num_cycles", 6)
        speed_percent = params.get("speed_percent", 50)
        cmd = FlipCommand.create(num_cycles, speed_percent)

        if not self._validate_command(cmd, CommandParser.validate_flip):
            return False

        for attempt in range(max_retries):
            try:
                logger.info(f"  翻炒: {num_cycles} 循環，{speed_percent}% 速度，雙臂協同")

                # FLIP 兩臂逐循環用 SYNC_STEP 會合，指令必須同時送給兩邊
                responses = self.comms.send_command_dual(cmd)
                if responses.get("F60_F") == "OK" and responses.get("F60_R") == "OK":
                    logger.info(f"  ✓ 翻炒完成")
                    return True
                else:
                    logger.warning(f"  ⚠️ 翻炒回應異常: F60_F={responses.get('F60_F')}, F60_R={responses.get('F60_R')}")
                    
            except Exception as e:
                logger.warning(f"  ⚠️ 翻炒嘗試 {attempt+1}/{max_retries} 失敗: {e}")
            
            if attempt < max_retries - 1:
                time.sleep(RetryPolicy.RETRY_DELAY_SEC)
        
        logger.error(f"  ✗ 翻炒失敗 (重試 {max_retries} 次)")
        return False
    
    def _handle_home(self, location: str, params: Dict, max_retries: int) -> bool:
        """處理復歸（兩臂都要回原點）"""
        # AS 的 DO_HOME 會檢查 arm == $this_arm，各臂只認自己的名稱，
        # 所以兩邊各送各的。食譜裡的 params["arm"] 只是主導臂標示，
        # 不代表只復歸那一支——收工時兩臂都得回原點。
        cmds = {a: HomeCommand.create(a) for a in ("F60_F", "F60_R")}

        for c in cmds.values():
            if not self._validate_command(c, CommandParser.validate_home):
                return False

        # 復歸失敗是致命的，不允許重試
        try:
            logger.info(f"  復歸: F60_F + F60_R → {location}")

            responses = self.comms.send_command_dual(cmds)
            response = f"F60_F={responses.get('F60_F')}, F60_R={responses.get('F60_R')}"

            if responses.get("F60_F") == "OK" and responses.get("F60_R") == "OK":
                logger.info(f"  ✓ 復歸完成")
                return True
            else:
                logger.error(f"  ✗ 復歸失敗: {response}")
                return False
                
        except Exception as e:
            logger.error(f"  ✗ 復歸異常: {e}")
            return False
    
    # ========================================================================
    # 系統初始化
    # ========================================================================
    
    def _initialize_arms(self) -> bool:
        """初始化機器人手臂"""
        logger.info("初始化機器人手臂...")
        
        try:
            # 檢查兩臂狀態
            for arm in ["F60_F", "F60_R"]:
                response = self.comms.send_command(arm, StatusCommand.create(arm))
                
                if response == "OK":
                    logger.info(f"  ✓ {arm} 狀態正常")
                else:
                    logger.error(f"  ✗ {arm} 狀態異常: {response}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"✗ 初始化失敗: {e}")
            return False
    
    # ========================================================================
    # 查詢與報告
    # ========================================================================
    
    def get_progress(self) -> Dict:
        """取得進度信息"""
        if not self.phases:
            return {"total_phases": 0, "completed_phases": 0, "progress_percent": 0}
        
        progress_percent = (self.current_phase_index / len(self.phases)) * 100
        
        return {
            "total_phases": len(self.phases),
            "completed_phases": self.current_phase_index,
            "progress_percent": progress_percent,
            "current_phase": self.phases[self.current_phase_index].phase.value if self.current_phase_index < len(self.phases) else "DONE",
        }
    
    def print_execution_report(self):
        """列印執行報告"""
        if not self.phase_logs:
            logger.info("無執行日誌")
            return
        
        logger.info("\n" + "="*60)
        logger.info("執行報告")
        logger.info("="*60)
        
        success_count = sum(1 for log in self.phase_logs if log.status == PhaseStatus.SUCCESS)
        total_count = len(self.phase_logs)
        
        logger.info(f"成功: {success_count}/{total_count}")
        
        for i, log in enumerate(self.phase_logs, 1):
            status_str = "✓" if log.status == PhaseStatus.SUCCESS else "✗"
            logger.info(f"  [{i}] {status_str} {log.phase.value:15} ({log.duration_sec:.1f}s)")
            
            if log.error_msg:
                logger.info(f"       錯誤: {log.error_msg}")
        
        if self.start_time and self.end_time:
            total_time = self.end_time - self.start_time
            logger.info(f"\n總耗時: {total_time:.1f} 秒")
        
        logger.info("="*60 + "\n")

