"""
SmartCook 相機排錯工具 (Camera Test)
開啟相機、即時預覽畫面，按下 SPACE 才拍照存檔，按 ESC/q 結束預覽。
不需要 YOLO 或標定資料，跟 vision_skeleton.py 的偵測流程無關。

用法:
    python camera_test.py                 # 使用預設攝影機 (index 0)
    python camera_test.py --index 1       # 指定攝影機編號
    python camera_test.py --warmup 10     # 開啟預覽前先丟棄 N 張畫面 (讓自動曝光穩定)
    python camera_test.py --brightness 60 # 拍照太暗時調高亮度 (預設 0 不調整，跟 yolo_camera_test.py 一致；調高會加重反光)
    python camera_test.py --width 1280 --height 720   # 覺得畫質不好時，嘗試更高解析度

預覽視窗操作:
    SPACE       拍照存檔 (可連續按，依序存成 capture_001.jpg, capture_002.jpg ...)
    + / -       手動調整對焦 (畫面靜止不動時還是模糊，通常是對焦沒對準)
    ESC 或 q    結束預覽
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from config_vision import VisionProcessingConfig

CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
CAPTURE_NAME_RE = re.compile(r"^capture_(\d{3})\.jpg$")


def next_capture_path() -> Path:
    """依 captures 資料夾裡現有的 capture_NNN.jpg 找出下一個序號 (第一張是 001)"""
    existing = [
        int(m.group(1))
        for f in CAPTURE_DIR.glob("capture_*.jpg")
        if (m := CAPTURE_NAME_RE.match(f.name))
    ]
    next_seq = max(existing, default=0) + 1
    return CAPTURE_DIR / f"capture_{next_seq:03d}.jpg"


def save_frame(cv2, frame) -> Path:
    """把畫面存成下一個序號的檔案，回傳存檔路徑"""
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = next_capture_path()

    # cv2.imwrite() 在 Windows 上不支援含中文的路徑（內部用 fopen，會靜默失敗）
    # 改用 imencode + ndarray.tofile()，這條路徑處理才是 Unicode-safe
    ok, buf = cv2.imencode(".jpg", frame)
    if not ok:
        raise RuntimeError("影像編碼失敗 (cv2.imencode 回傳 False)")
    buf.tofile(str(out_path))
    return out_path


def run_preview_session(
    camera_index: int, warmup_frames: int, brightness: float, width: int, height: int
) -> int:
    """
    開啟相機即時預覽，按 SPACE 拍照存檔，按 ESC/q 結束

    Args:
        camera_index: 攝影機裝置編號 (通常內建 0，外接 USB 相機常是 1)
        warmup_frames: 開啟預覽前丟棄的畫面數，避免用到自動曝光/白平衡還沒穩定的第一張
        brightness: 拍照後加亮的程度 (0 表示不調整)
        width: 要求的畫面寬度
        height: 要求的畫面高度

    Returns:
        這次 session 總共存了幾張照片

    Raises:
        RuntimeError: 相機打不開，或連續讀取畫面都失敗
    """
    try:
        import cv2
    except ImportError:
        raise RuntimeError(
            "找不到 opencv-python，請先執行：pip install opencv-python"
        )

    fps = VisionProcessingConfig.CAMERA_FPS

    # Windows 預設的 MSMF 後端常常不支援 CAP_PROP_FOCUS 等屬性控制，改用 DirectShow 後端相容性較好
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(
            f"無法開啟攝影機 index={camera_index}。"
            f"檢查：1) 相機是否已接上電腦 2) 是否被其他程式占用 3) 換一個 --index 再試"
        )

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)

    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if (actual_width, actual_height) != (width, height):
        print(
            f"⚠ 要求解析度 {width}x{height}，但相機實際回報 {actual_width}x{actual_height}"
            f"（相機可能不支援要求的解析度，換一個 --width/--height 試試）"
        )
    else:
        print(f"解析度: {actual_width}x{actual_height}")

    # 關閉自動對焦，改成手動調整（畫面靜止仍模糊時，通常是自動對焦沒對準）
    autofocus_supported = cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
    focus = int(cap.get(cv2.CAP_PROP_FOCUS)) if autofocus_supported else 0
    focus_supported = autofocus_supported
    if not autofocus_supported:
        print("⚠ 這台相機不支援程式控制對焦 (CAP_PROP_AUTOFOCUS)，只能靠鏡頭上的實體對焦環或調整拍攝距離")

    window_name = "SmartCook Camera Preview - SPACE: 拍照 / +-: 對焦 / ESC or q: 結束"
    saved_count = 0

    try:
        for _ in range(warmup_frames):
            cap.read()

        while True:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError("相機已開啟，但讀取畫面失敗 (cap.read() 回傳 False)")

            if brightness:
                frame = cv2.convertScaleAbs(frame, alpha=1.0, beta=brightness)

            if focus_supported:
                cv2.putText(
                    frame, f"focus: {focus}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2,
                )

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF

            if key == 32:  # SPACE
                out_path = save_frame(cv2, frame)
                saved_count += 1
                print(f"✓ 拍照成功，已存到: {out_path.resolve()}")
            elif key in (27, ord("q")):  # ESC or q
                break
            elif key in (ord("+"), ord("=")) and focus_supported:
                focus = min(focus + 5, 255)
                cap.set(cv2.CAP_PROP_FOCUS, focus)
                print(f"對焦值: {focus}")
            elif key == ord("-") and focus_supported:
                focus = max(focus - 5, 0)
                cap.set(cv2.CAP_PROP_FOCUS, focus)
                print(f"對焦值: {focus}")

        return saved_count
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=int, default=0, help="攝影機裝置編號 (預設 0)")
    parser.add_argument("--warmup", type=int, default=5, help="開啟預覽前丟棄的暖機畫面數 (預設 5)")
    parser.add_argument("--brightness", type=float, default=0, help="拍照後加亮程度 (預設 0 不調整；調高容易讓反光處死白，跟 yolo_camera_test.py 保持一致)")
    default_width, default_height = VisionProcessingConfig.CAMERA_RESOLUTION
    parser.add_argument("--width", type=int, default=default_width, help=f"畫面寬度 (預設 {default_width})")
    parser.add_argument("--height", type=int, default=default_height, help=f"畫面高度 (預設 {default_height})")
    args = parser.parse_args()

    print(f"開啟攝影機 index={args.index} ，預覽視窗開啟後按 SPACE 拍照、ESC/q 結束 ...")
    try:
        saved_count = run_preview_session(
            args.index, args.warmup, args.brightness, args.width, args.height
        )
    except RuntimeError as e:
        print(f"✗ 失敗: {e}")
        return 1

    print(f"\n預覽結束，總共拍了 {saved_count} 張照片")
    return 0


if __name__ == "__main__":
    sys.exit(main())
