"""
SmartCook 取料+切割整合測試 (Pickup + Chop Test)
跳過選單/放置/翻炒流程，只確認 PICKUP → CHOP 的完整動作。
使用固定參數（x=0, y=0, angle=0），視覺定位先跳過。

用法:
    python test_pickup_chop.py CUCUMBER        # 小黃瓜：取料 → 切7刀
    python test_pickup_chop.py CARROT          # 紅蘿蔔：取料 → 切7刀
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from comms_connection_skeleton import CommsManager
from config_commands import PickupCommand, ChopCommand

FOOD_LOCATIONS = {
    "CUCUMBER": "PICKUP_CUCUMBER",
    "CARROT": "PICKUP_CARROT",
}

# 切割參數：[刀數, 厚度 mm]
CUT_PARAMS = {
    "CUCUMBER": [7, 4.0],
    "CARROT": [7, 4.0],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        nargs="?",
        default="CUCUMBER",
        help="食材類型 (CUCUMBER/CARROT，預設 CUCUMBER)",
    )
    parser.add_argument("--arm", default="F60_F", help="主導臂 (預設 F60_F)")
    args = parser.parse_args()

    target = args.target.upper()
    if target not in FOOD_LOCATIONS:
        print(f"✗ 不支援的菜色: {args.target}")
        print(f"  支援: {list(FOOD_LOCATIONS.keys())}")
        print("  備註: 生菜已改為直接進混拌區，不經過 CHOP")
        return 1

    location = FOOD_LOCATIONS[target]

    # ================================================================
    # 步驟 1: 使用固定參數（視覺定位先跳過）
    # ================================================================
    x_mm, y_mm, angle_deg = 0.0, 0.0, 0.0
    print(f"使用固定參數: x={x_mm}mm, y={y_mm}mm, angle={angle_deg}°（視覺定位待實現）")

    # ================================================================
    # 步驟 2: 連接兩臂
    # ================================================================
    manager = CommsManager()
    print("\n正在連線 F60_F 與 F60_R ...")
    if not manager.connect_all():
        print("✗ 連線失敗")
        return 1
    print("✓ F60_F 與 F60_R 都已連線")

    # ================================================================
    # 步驟 3: 送出 PICKUP 指令
    # ================================================================
    pickup_cmd = PickupCommand.create(location, args.arm, x_mm, y_mm, angle_deg)
    print(f"\n[PICKUP] 送出: {pickup_cmd}")
    responses = manager.send_command_dual(pickup_cmd)
    print(f"  F60_F 回應: {responses.get('F60_F')}")
    print(f"  F60_R 回應: {responses.get('F60_R')}")

    if responses.get("F60_F") != "OK" or responses.get("F60_R") != "OK":
        print("✗ PICKUP 失敗，中止")
        manager.disconnect_all()
        return 1
    print("✓ PICKUP 完成")

    # ================================================================
    # 步驟 4: 送出 CHOP 指令
    # ================================================================
    num_cuts, thickness_mm = CUT_PARAMS[target]
    chop_cmd = ChopCommand.create(target, num_cuts, thickness_mm)
    print(f"\n[CHOP] 送出: {chop_cmd}")
    responses = manager.send_command_dual(chop_cmd)
    print(f"  F60_F 回應: {responses.get('F60_F')}")
    print(f"  F60_R 回應: {responses.get('F60_R')}")

    manager.disconnect_all()

    if responses.get("F60_F") == "OK" and responses.get("F60_R") == "OK":
        print(f"\n✓ PICKUP + CHOP 完成 ({target}, {num_cuts} 刀)")
        return 0

    print("\n✗ CHOP 失敗")
    print("  常見錯誤:")
    print("  - E4023: 雙臂同步超時（檢查 AS 程式 I/O 交握）")
    print("  - E4005: 菜色不支援或參數無效")
    return 1


if __name__ == "__main__":
    sys.exit(main())
