#!/usr/bin/env python3
"""
完整三菜沙拉工作流程測試
繞過視覺系統，使用固定參數測試整個 PICKUP → CHOP → PLACE → FLIP → POUR 流程

流程：
1. 小黃瓜：PICKUP → CHOP(5刀,4mm) → PLACE 到 WAIT_ZONE_1
2. 紅蘿蔔：PICKUP → CHOP(5刀,4mm) → PLACE 到 MIX_ZONE
3. 生菜：PICKUP → PLACE 到 MIX_ZONE（不切）
4. 取回小黃瓜：PLACE 從 WAIT_ZONE_1 → MIX_ZONE
5. 翻炒：FLIP(6 循環, 50% 速度)
6. 倒盤：PLACE 從 MIX_ZONE → SALAD_BOWL（POUR 方式）
"""

import time
import sys
from pathlib import Path

# 加入 src 路徑
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config_phase import Phase, MenuRecipes, PhaseInstruction


class SaladWorkflowTest:
    """三菜沙拉工作流程測試"""

    def __init__(self):
        self.log_lines = []
        self.current_step = 0
        self.total_steps = 0

    def log(self, msg: str):
        """記錄訊息"""
        self.log_lines.append(msg)
        print(msg)

    def print_header(self, title: str):
        """列印標題"""
        self.log(f"\n{'='*70}")
        self.log(f"  {title}")
        self.log(f"{'='*70}\n")

    def print_step(self, step_num: int, title: str, details: str = ""):
        """列印步驟"""
        self.current_step = step_num
        self.log(f"\n【步驟 {step_num}】{title}")
        if details:
            self.log(f"  {details}")

    def simulate_command(self, cmd: str, params: dict):
        """模擬機器人指令"""
        self.log(f"  → 發送指令: {cmd}")
        for key, val in params.items():
            self.log(f"    {key}: {val}")
        self.log(f"  ✓ 執行完成\n")
        time.sleep(0.5)  # 模擬執行時間

    def run_workflow(self):
        """執行完整工作流程"""
        self.print_header("完整三菜沙拉工作流程測試")

        self.log("配置參數（固定值）：")
        self.log("  視覺座標：x=0, y=0, angle=0")
        self.log("  小黃瓜：5 刀，4mm")
        self.log("  紅蘿蔔：5 刀，4mm")
        self.log("  生菜：不切，直接進混拌區\n")

        step = 1

        # ===== 步驟 1-3：小黃瓜 =====
        self.print_step(step, "小黃瓜 - 取料")
        self.simulate_command("DO_PICKUP", {
            "location": "PICKUP_CUCUMBER",
            "arm": "F60_F",
            "x_mm": 0,
            "y_mm": 0,
            "angle_deg": 0,
        })
        step += 1

        self.print_step(step, "小黃瓜 - 切割")
        self.simulate_command("DO_CHOP", {
            "food": "CUCUMBER",
            "cuts": 5,
            "thickness_mm": 4,
        })
        step += 1

        self.print_step(step, "小黃瓜 - 放置到暫放區1")
        self.simulate_command("DO_PLACE", {
            "source": "WORK_CHOP_ZONE",
            "location": "WAIT_ZONE_1",
            "method": "SCOOP",
        })
        step += 1

        # ===== 步驟 4-6：紅蘿蔔 =====
        self.print_step(step, "紅蘿蔔 - 取料")
        self.simulate_command("DO_PICKUP", {
            "location": "PICKUP_CARROT",
            "arm": "F60_F",
            "x_mm": 0,
            "y_mm": 0,
            "angle_deg": 0,
        })
        step += 1

        self.print_step(step, "紅蘿蔔 - 切割")
        self.simulate_command("DO_CHOP", {
            "food": "CARROT",
            "cuts": 5,
            "thickness_mm": 4,
        })
        step += 1

        self.print_step(step, "紅蘿蔔 - 放置到混拌區")
        self.simulate_command("DO_PLACE", {
            "source": "WORK_CHOP_ZONE",
            "location": "MIX_ZONE",
            "method": "SCOOP",
        })
        step += 1

        # ===== 步驟 7-8：生菜 =====
        self.print_step(step, "生菜 - 取料")
        self.simulate_command("DO_PICKUP", {
            "location": "PICKUP_LETTUCE",
            "arm": "F60_F",
            "x_mm": 0,
            "y_mm": 0,
            "angle_deg": 0,
        })
        step += 1

        self.print_step(step, "生菜 - 放置到混拌區（不切）")
        self.simulate_command("DO_PLACE", {
            "source": "WORK_CHOP_ZONE",
            "location": "MIX_ZONE",
            "method": "SCOOP",
        })
        step += 1

        # ===== 步驟 9：取回小黃瓜 =====
        self.print_step(step, "取回小黃瓜 - 從暫放區1 → 混拌區")
        self.simulate_command("DO_PLACE", {
            "source": "WAIT_ZONE_1",
            "location": "MIX_ZONE",
            "method": "SCOOP",
        })
        step += 1

        self.print_header("✓ 三種食材全數進入混拌區，準備翻炒")

        # ===== 步驟 10：翻炒 =====
        self.print_step(step, "翻炒 - 在混拌區進行")
        self.simulate_command("DO_FLIP", {
            "location": "MIX_ZONE",
            "cycles": 6,
            "speed_pct": 50,
            "estimated_time_sec": 18,
        })
        step += 1

        self.print_header("✓ 翻炒完成，準備倒盤")

        # ===== 步驟 11：倒盤 =====
        self.print_step(step, "倒盤 - 從混拌區 → 沙拉盤")
        self.log("  詳細說明：")
        self.log("    source: MIX_ZONE（混拌區的沙拉）")
        self.log("    location: SALAD_BOWL（沙拉盤）")
        self.log("    method: POUR（傾倒方式）")
        self.simulate_command("DO_PLACE", {
            "source": "MIX_ZONE",
            "location": "SALAD_BOWL",
            "method": "POUR",
        })
        step += 1

        self.print_header("✓ 完整工作流程測試完成！")

        self.log("\n工作流程總結：")
        self.log(f"  總步驟數：{step - 1}")
        self.log(f"  預估執行時間：約 2-3 分鐘（包含切割、翻炒、倒盤）")
        self.log("\n預期結果：")
        self.log("  ✓ 三種食材依序進入混拌區")
        self.log("  ✓ 翻炒 6 個循環，約 18 秒")
        self.log("  ✓ 最終倒入沙拉盤完成")

    def save_log(self):
        """保存日誌"""
        log_file = Path(__file__).parent / "test_full_salad_workflow.log"
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(self.log_lines))
        self.log(f"\n日誌已保存：{log_file}")


if __name__ == "__main__":
    test = SaladWorkflowTest()
    test.run_workflow()
    test.save_log()
