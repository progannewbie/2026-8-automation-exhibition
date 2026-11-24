"""
SmartCook 翻炒單獨測試工具 (Flip-Only Test)
跳過選單與取料/切割/放置流程，只確認雙臂連線後直接送出 FLIP 指令。
用於 7/31 排程要求的「翻炒軌跡空檯面 10% 速度驗證」。

用法:
    python test_flip.py
"""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from comms_connection_skeleton import CommsManager

FLIP_CYCLES = 1
FLIP_SPEED_PERCENT = 10  # 空檯面低速驗證用，確認軌跡與雙臂時序安全後再拉高

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
    )

    manager = CommsManager()

    print("正在連線 F60_F 與 F60_R ...")
    if not manager.connect_all():
        print("\n✗ 連線失敗，尚未送出任何指令。")
        print("  請檢查：兩隻手臂電源、網路線、AS 程式是否已在控制器上 EXECUTE。")
        return 1

    print("\n✓ F60_F 與 F60_R 都已連線")

    cmd = f"FLIP,{FLIP_CYCLES},{FLIP_SPEED_PERCENT}"
    print(f"\n送出: {cmd} (同時送給兩臂)")
    responses = manager.send_command_dual(cmd)
    print(f"  F60_F 回應: {responses.get('F60_F')}")
    print(f"  F60_R 回應: {responses.get('F60_R')}")

    manager.disconnect_all()

    if responses.get("F60_F") == "OK" and responses.get("F60_R") == "OK":
        print("\n✓ 翻炒動作完成")
        return 0

    print("\n✗ 翻炒動作異常，請看上面的回應內容（例如 ERROR,E4023 代表雙臂 SYNC_STEP 逾時）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
