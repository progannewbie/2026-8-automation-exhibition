"""
SmartCook PICKUP 固定座標測試工具 (No-Vision Fixed-Coordinate Test)
跳過 YOLO 視覺定位，直接用固定座標送出 PICKUP 指令，用來單獨測試 DO_PICKUP
的動作序列（就緒→下降→集中→抬起→移至切割區），不需要相機/YOLO 環境。

用法:
    python test_pickup_fixed.py CUCUMBER
    python test_pickup_fixed.py CARROT
    python test_pickup_fixed.py ROMAINE
    python test_pickup_fixed.py CUCUMBER --x -70 --y 0 --angle 0   # 預設值，可覆蓋
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from comms_connection_skeleton import CommsManager
from config_commands import PickupCommand

FOOD_LOCATIONS = {
    "CUCUMBER": "PICKUP_CUCUMBER",
    "CARROT": "PICKUP_CARROT",
    "ROMAINE": "PICKUP_ROMAINE",
}

DEFAULT_X_MM = -70.0
DEFAULT_Y_MM = 0.0
DEFAULT_ANGLE_DEG = 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("food", help="食材類型 (CUCUMBER/CARROT/ROMAINE)")
    parser.add_argument("--arm", default="F60_F", help="主導臂 (預設 F60_F)")
    parser.add_argument("--x", type=float, default=DEFAULT_X_MM, help=f"固定 X 座標 mm (預設 {DEFAULT_X_MM})")
    parser.add_argument("--y", type=float, default=DEFAULT_Y_MM, help=f"固定 Y 座標 mm (預設 {DEFAULT_Y_MM})")
    parser.add_argument("--angle", type=float, default=DEFAULT_ANGLE_DEG, help=f"固定角度 deg (預設 {DEFAULT_ANGLE_DEG})")
    args = parser.parse_args()

    food = args.food.upper()
    if food not in FOOD_LOCATIONS:
        print(f"✗ 不認得的食材: {args.food}，可用: {list(FOOD_LOCATIONS)}")
        return 1
    location = FOOD_LOCATIONS[food]

    print(f"固定座標測試（不經過 YOLO）: location={location}, x={args.x}mm, y={args.y}mm, angle={args.angle}deg")

    manager = CommsManager()
    print("\n正在連線 F60_F 與 F60_R ...")
    if not manager.connect_all():
        print("✗ 連線失敗，尚未送出任何指令。")
        print("  請檢查：兩隻手臂電源、網路線、AS 程式是否已在控制器上 EXECUTE。")
        return 1
    print("✓ F60_F 與 F60_R 都已連線")

    cmd = PickupCommand.create(location, args.arm, args.x, args.y, args.angle)
    print(f"\n送出: {cmd} (同時送給兩臂)")
    responses = manager.send_command_dual(cmd)
    print(f"  F60_F 回應: {responses.get('F60_F')}")
    print(f"  F60_R 回應: {responses.get('F60_R')}")

    manager.disconnect_all()

    if responses.get("F60_F") == "OK" and responses.get("F60_R") == "OK":
        print("\n✓ 取料完成")
        return 0

    print("\n✗ 取料異常，請看上面的回應內容（例如 ERROR,E4023 代表雙臂 SYNC_STEP 逾時，E4002 代表位置無效）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
