"""
SmartCook 相機排錯工具 (Camera Test)
開啟相機、拍一張照片存檔，用來確認相機能否正常連接與拍照。
不需要 YOLO 或標定資料，跟 vision_skeleton.py 的偵測流程無關。

用法:
    python camera_test.py                 # 使用預設攝影機 (index 0)
    python camera_test.py --index 1       # 指定攝影機編號
    python camera_test.py --warmup 10     # 拍照前先丟棄 N 張畫面 (讓自動曝光穩定)
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from config_vision import VisionProcessingConfig

CAPTURE_DIR = Path("captures")


def capture_one_photo(camera_index: int, warmup_frames: int) -> Path:
    """
    開啟相機、拍一張照片並存檔

    Args:
        camera_index: 攝影機裝置編號 (通常內建 0，外接 USB 相機常是 1)
        warmup_frames: 正式拍照前丟棄的畫面數，避免用到自動曝光/白平衡還沒穩定的第一張

    Returns:
        存檔後的照片路徑

    Raises:
        RuntimeError: 相機打不開，或連續讀取畫面都失敗
    """
    try:
        import cv2
    except ImportError:
        raise RuntimeError(
            "找不到 opencv-python，請先執行：pip install opencv-python"
        )

    width, height = VisionProcessingConfig.CAMERA_RESOLUTION
    fps = VisionProcessingConfig.CAMERA_FPS

    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(
            f"無法開啟攝影機 index={camera_index}。"
            f"檢查：1) 相機是否已接上電腦 2) 是否被其他程式占用 3) 換一個 --index 再試"
        )

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)

    try:
        for _ in range(warmup_frames):
            cap.read()

        ok, frame = cap.read()
        if not ok:
            raise RuntimeError("相機已開啟，但讀取畫面失敗 (cap.read() 回傳 False)")

        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = CAPTURE_DIR / f"capture_{timestamp}.jpg"
        cv2.imwrite(str(out_path), frame)

        return out_path
    finally:
        cap.release()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=int, default=0, help="攝影機裝置編號 (預設 0)")
    parser.add_argument("--warmup", type=int, default=5, help="拍照前丟棄的暖機畫面數 (預設 5)")
    args = parser.parse_args()

    print(f"開啟攝影機 index={args.index} ...")
    try:
        photo_path = capture_one_photo(args.index, args.warmup)
    except RuntimeError as e:
        print(f"✗ 拍照失敗: {e}")
        return 1

    print(f"✓ 拍照成功，已存到: {photo_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
