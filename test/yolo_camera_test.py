"""
SmartCook YOLO 即時偵測測試工具 (YOLO Camera Test)
開啟相機、即時預覽畫面，按下 SPACE 就對當下畫面跑一次 YOLO 偵測，
把偵測框、類別、信心度畫在畫面上並存檔，按 ESC/q 結束預覽。
用來確認 YOLO 模型接得起來、也能實際認出食材。

跟 camera_test.py 的差別：camera_test.py 純拍照，不跑模型；這支會載入
YOLOConfig.MODEL_PATH 指定的模型並執行推理。

用法:
    python yolo_camera_test.py                 # 使用預設攝影機 (index 0)
    python yolo_camera_test.py --index 1       # 指定攝影機編號
    python yolo_camera_test.py --conf 0.5      # 覺得偵測不到食材時，先調低信心閾值試試
    python yolo_camera_test.py --warmup 10     # 開啟預覽前先丟棄 N 張畫面 (讓自動曝光穩定)

預覽視窗操作:
    SPACE       對目前畫面跑一次 YOLO 偵測，結果畫框存檔 (yolo_001.jpg, yolo_002.jpg ...)
                並在終端機印出偵測到的食材、信心度、像素座標
    ESC 或 q    結束預覽
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from config_vision import VisionProcessingConfig, YOLOConfig
from vision_skeleton import YOLODetector

CAPTURE_DIR = Path(__file__).resolve().parent / "captures"
CAPTURE_NAME_RE = re.compile(r"^yolo_(\d{3})\.jpg$")

# 畫框用的顏色，依 class_id 輪流挑選 (BGR)
BOX_COLORS = [
    (0, 255, 0),
    (0, 165, 255),
    (255, 128, 0),
    (0, 0, 255),
    (255, 0, 255),
]


def next_capture_path() -> Path:
    """依 captures 資料夾裡現有的 yolo_NNN.jpg 找出下一個序號 (第一張是 001)"""
    existing = [
        int(m.group(1))
        for f in CAPTURE_DIR.glob("yolo_*.jpg")
        if (m := CAPTURE_NAME_RE.match(f.name))
    ]
    next_seq = max(existing, default=0) + 1
    return CAPTURE_DIR / f"yolo_{next_seq:03d}.jpg"


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


def draw_detections(cv2, frame, detections):
    """把 YOLODetector.detect() 的結果畫成框、類別標籤、信心度、座標與旋轉角"""
    for det in detections:
        color = BOX_COLORS[det["class_id"] % len(BOX_COLORS)]
        cx, cy = det["center_x_pixel"], det["center_y_pixel"]
        w, h = det["width_pixel"], det["height_pixel"]
        angle = det["angle_deg"]
        is_real_angle = det.get("angle_source") == "obb"

        if is_real_angle:
            # OBB 模型有真正的旋轉角，畫實際旋轉後的框
            box_pts = cv2.boxPoints(((cx, cy), (w, h), angle)).astype(int)
            cv2.drawContours(frame, [box_pts], 0, color, 2)
            x1, y1 = int(cx - w / 2), int(cy - h / 2)  # 標籤位置仍用軸對齊框的左上角
        else:
            x1, y1 = int(cx - w / 2), int(cy - h / 2)
            x2, y2 = int(cx + w / 2), int(cy + h / 2)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        cv2.circle(frame, (int(cx), int(cy)), 4, color, -1)

        angle_text = f"{angle:.1f}deg" if is_real_angle else f"~{angle:.0f}deg(est)"
        line1 = f"{det['class_name']} {det['confidence']:.2f}"
        line2 = f"({cx:.0f},{cy:.0f}) {angle_text}"

        (tw1, th1), _ = cv2.getTextSize(line1, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        (tw2, th2), _ = cv2.getTextSize(line2, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        box_w = max(tw1, tw2) + 6
        box_h = th1 + th2 + 14

        label_y1 = max(y1 - box_h, 0)
        cv2.rectangle(frame, (x1, label_y1), (x1 + box_w, y1), color, -1)
        cv2.putText(
            frame, line1, (x1 + 3, label_y1 + th1 + 3),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2,
        )
        cv2.putText(
            frame, line2, (x1 + 3, label_y1 + th1 + th2 + 9),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1,
        )
    return frame


def run_preview_session(
    detector, camera_index: int, warmup_frames: int, width: int, height: int
) -> int:
    """
    開啟相機即時預覽，按 SPACE 對當下畫面跑 YOLO 偵測並存檔，按 ESC/q 結束

    Returns:
        這次 session 總共跑了幾次偵測並存檔

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

    # Windows 預設的 MSMF 後端常常不支援屬性控制，改用 DirectShow 後端相容性較好
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(
            f"無法開啟攝影機 index={camera_index}。"
            f"檢查：1) 相機是否已接上電腦 2) 是否被其他程式占用 3) 換一個 --index 再試"
        )

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)

    window_name = "SmartCook YOLO Test - SPACE: 偵測並存檔 / ESC or q: 結束"
    saved_count = 0

    try:
        for _ in range(warmup_frames):
            cap.read()

        while True:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError("相機已開啟，但讀取畫面失敗 (cap.read() 回傳 False)")

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF

            if key == 32:  # SPACE
                detections = detector.detect(frame)
                annotated = draw_detections(cv2, frame.copy(), detections)
                out_path = save_frame(cv2, annotated)
                saved_count += 1

                if detections:
                    print(f"✓ 偵測到 {len(detections)} 個食材，已存到: {out_path.resolve()}")
                    for det in detections:
                        angle_note = "" if det.get("angle_source") == "obb" else " (估計值，模型非 OBB，僅供參考)"
                        print(
                            f"    {det['class_name']:10s} conf={det['confidence']:.2f}"
                            f"  中心像素=({det['center_x_pixel']:.0f}, {det['center_y_pixel']:.0f})"
                            f"  旋轉角={det['angle_deg']:.1f}°{angle_note}"
                        )
                else:
                    print(f"⚠ 沒有偵測到任何食材 (信心閾值={YOLOConfig.CONFIDENCE_THRESHOLD})，已存到: {out_path.resolve()}")

                cv2.imshow(window_name, annotated)
                cv2.waitKey(500)  # 讓標註畫面停留一下方便看清楚

            elif key in (27, ord("q")):  # ESC or q
                break

        return saved_count
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=int, default=0, help="攝影機裝置編號 (預設 0)")
    parser.add_argument("--warmup", type=int, default=5, help="開啟預覽前丟棄的暖機畫面數 (預設 5)")
    parser.add_argument("--conf", type=float, default=None, help="覆蓋 YOLOConfig 的信心閾值 (預設用設定檔的值)")
    default_width, default_height = VisionProcessingConfig.CAMERA_RESOLUTION
    parser.add_argument("--width", type=int, default=default_width, help=f"畫面寬度 (預設 {default_width})")
    parser.add_argument("--height", type=int, default=default_height, help=f"畫面高度 (預設 {default_height})")
    args = parser.parse_args()

    if args.conf is not None:
        YOLOConfig.CONFIDENCE_THRESHOLD = args.conf

    print(f"載入 YOLO 模型: {YOLOConfig.MODEL_PATH}")
    detector = YOLODetector()
    if detector.model is None:
        print("✗ YOLO 模型載入失敗，請看上面的錯誤訊息（常見原因：模型檔案不存在、ultralytics 未安裝）")
        return 1
    print(f"✓ 模型已載入，信心閾值={YOLOConfig.CONFIDENCE_THRESHOLD}，類別={list(YOLOConfig.CLASSES.values())}")

    print(f"\n開啟攝影機 index={args.index} ，預覽視窗開啟後按 SPACE 跑偵測、ESC/q 結束 ...")
    try:
        saved_count = run_preview_session(
            detector, args.index, args.warmup, args.width, args.height
        )
    except RuntimeError as e:
        print(f"✗ 失敗: {e}")
        return 1

    print(f"\n預覽結束，總共跑了 {saved_count} 次偵測")
    return 0


if __name__ == "__main__":
    sys.exit(main())
