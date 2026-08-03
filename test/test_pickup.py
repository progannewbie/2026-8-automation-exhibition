"""
SmartCook 取料單獨測試工具 (Pickup-Only Test)
跳過選單/切割/放置流程，只確認雙臂連線後，用視覺定位＋送出 PICKUP 指令。

食材點位 (PICKUP_CUCUMBER/CARROT/CORN) 會先拍照跑 YOLO，偵測不到就中止、
不送指令；WAIT_ZONE 這類固定暫存區沒有視覺目標，直接送 0,0,0。

用法:
    python test_pickup.py CUCUMBER        # 拍照偵測小黃瓜，定位後送 PICKUP
    python test_pickup.py CARROT
    python test_pickup.py CORN
    python test_pickup.py WAIT_ZONE       # 固定暫存區，不經過視覺
    python test_pickup.py CUCUMBER --conf 0.5   # 偵測不到時，先調低信心閾值試試
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from comms_connection_skeleton import CommsManager
from vision_skeleton import VisionSystem
from config_vision import YOLOConfig
from config_commands import PickupCommand

FOOD_LOCATIONS = {
    "CUCUMBER": "PICKUP_CUCUMBER",
    "CARROT": "PICKUP_CARROT",
    "CORN": "PICKUP_CORN",
}
FIXED_LOCATIONS = ["WAIT_ZONE", "MIX_ZONE"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        help="食材類型 (CUCUMBER/CARROT/CORN) 或固定位置 (WAIT_ZONE/MIX_ZONE)",
    )
    parser.add_argument("--arm", default="F60_F", help="主導臂 (預設 F60_F)")
    parser.add_argument("--conf", type=float, default=None, help="覆蓋 YOLO 信心閾值")
    parser.add_argument("--camera-index", type=int, default=0, help="攝影機裝置編號 (預設 0)")
    args = parser.parse_args()

    target = args.target.upper()
    if target in FOOD_LOCATIONS:
        location = FOOD_LOCATIONS[target]
        food_type = target
    elif target in FIXED_LOCATIONS:
        location = target
        food_type = None
    else:
        print(f"✗ 不認得的目標: {args.target}")
        print(f"  食材: {list(FOOD_LOCATIONS)}　固定位置: {FIXED_LOCATIONS}")
        return 1

    if args.conf is not None:
        YOLOConfig.CONFIDENCE_THRESHOLD = args.conf

    x_mm, y_mm, angle_deg = 0.0, 0.0, 0.0

    if food_type:
        print(f"載入 YOLO 模型: {YOLOConfig.MODEL_PATH}")
        vision = VisionSystem()
        if vision.yolo_detector.model is None:
            print("✗ YOLO 模型載入失敗，無法定位食材")
            return 1

        print(f"開啟攝影機 index={args.camera_index} 拍照...")
        image = vision.capture_frame()
        if image is None:
            print("✗ 無法取得相機畫面")
            return 1

        detection = vision.get_location_and_angle_mm(food_type, image)
        if detection is None:
            print(f"✗ 未偵測到 {food_type}（信心閾值={YOLOConfig.CONFIDENCE_THRESHOLD}），中止，不送指令")
            return 1

        x_mm, y_mm, angle_deg = detection
        print(f"✓ 視覺定位 {food_type}: x={x_mm:.1f}mm, y={y_mm:.1f}mm, angle={angle_deg:.1f}°")
    else:
        print(f"目標 {location} 是固定暫存區，不經過視覺，直接送 0,0,0")

    manager = CommsManager()

    print("\n正在連線 F60_F 與 F60_R ...")
    if not manager.connect_all():
        print("✗ 連線失敗，尚未送出任何指令。")
        print("  請檢查：兩隻手臂電源、網路線、AS 程式是否已在控制器上 EXECUTE。")
        return 1
    print("✓ F60_F 與 F60_R 都已連線")

    cmd = PickupCommand.create(location, args.arm, x_mm, y_mm, angle_deg)
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
