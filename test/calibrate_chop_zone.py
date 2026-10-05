"""
SmartCook 切割區標定工具 (Chop Zone Calibration)

把切割區畫面的像素座標對應到左臂 F60_F 基座座標 (mm)，解出
config_vision.ChopZoneHomography 要用的 3×3 單應性。小黃瓜 / 紅蘿蔔「整根切完」
靠這組標定把食材兩端換算成左臂 X，決定起始格、刀數與換壓點（config_phase.ChopPlanConfig）。

標定步驟:
    1. 在切割區放一個小標記（例如瓶蓋、貼紙），用教導器讓左臂刀尖對準標記中心，
       記下教導器上的 X、Y（基座座標）
    2. 手臂退開到不擋畫面的位置
    3. 預覽視窗按 SPACE 凍結畫面，用滑鼠點標記中心，再到終端機輸入剛剛記下的 X,Y
    4. 換位置重複。至少 4 點、不要排成一直線：沿刀子方向（X）跟垂直方向（Y）都要拉開，
       建議 6～9 點，涵蓋小黃瓜可能落的整個範圍（例如 3×3 網格）
    5. 按 ENTER 計算，終端機會印出殘差和一段程式碼，貼回 src/config_vision.py 的
       ChopZoneHomography

用法:
    python calibrate_chop_zone.py                # 標定（預設攝影機 index 0）
    python calibrate_chop_zone.py --index 1      # 指定攝影機編號
    python calibrate_chop_zone.py --load         # 從上次存的點繼續（captures/chop_zone_points.json）
    python calibrate_chop_zone.py --check        # 標定貼回去之後，即時檢查量測、起始格與刀數

預覽視窗操作（標定模式）:
    SPACE   凍結 / 解除凍結畫面（凍結時才能點）
    滑鼠左鍵 在凍結畫面上點標記中心，接著到終端機輸入 X,Y
    u       刪掉最後一點
    ENTER   計算並印出結果（至少 4 點）
    ESC / q 結束（已點的點會自動存檔）
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from config_vision import ChopZoneHomography, VisionProcessingConfig

POINTS_FILE = Path(__file__).resolve().parent / "captures" / "chop_zone_points.json"
WINDOW = "chop zone calibration"


def open_camera(cv2, index: int, warmup: int):
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        sys.exit(f"✗ 無法開啟攝影機 index={index}")
    w, h = VisionProcessingConfig.CAMERA_RESOLUTION
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    for _ in range(warmup):
        cap.read()
    return cap


def save_points(points):
    POINTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    POINTS_FILE.write_text(json.dumps(points, ensure_ascii=False, indent=1), encoding="utf-8")


def draw_points(cv2, frame, points):
    for i, (u, v, x, y) in enumerate(points, 1):
        cv2.circle(frame, (int(u), int(v)), 5, (0, 0, 255), -1)
        cv2.putText(frame, f"{i}:({x:.0f},{y:.0f})", (int(u) + 6, int(v) - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)


def ask_xy(u: float, v: float):
    """終端機輸入左臂座標；空白取消"""
    while True:
        raw = input(f"  像素 ({u:.0f},{v:.0f}) 對應的左臂 X,Y (mm，空白取消): ").strip()
        if not raw:
            return None
        try:
            x, y = (float(t) for t in raw.replace("，", ",").split(","))
            return x, y
        except ValueError:
            print("  格式是 X,Y，例如 330.5,548.7")


def report(points):
    """解單應性、印殘差與要貼回 config_vision.py 的程式碼"""
    import numpy as np

    h = ChopZoneHomography.solve(points)
    ChopZoneHomography.H = h
    print("\n逐點殘差:")
    errs = []
    for u, v, x, y, px, py, err in ChopZoneHomography.residuals(points):
        errs.append(err)
        print(f"  ({u:.0f},{v:.0f}) → 實際 ({x:.1f},{y:.1f})  算出 ({px:.1f},{py:.1f})  誤差 {err:.2f}mm")
    print(f"RMS {float(np.sqrt(np.mean(np.square(errs)))):.2f}mm，最大 {max(errs):.2f}mm")
    if max(errs) > 5.0:
        print("⚠️ 最大誤差超過 5mm（一格刀距），建議檢查離群的那幾點重測")

    us = [p[0] for p in points]
    vs = [p[1] for p in points]
    print("\n===== 貼回 src/config_vision.py 的 ChopZoneHomography =====")
    print("    CALIBRATION_POINTS: List[Tuple[float, float, float, float]] = [")
    for u, v, x, y in points:
        print(f"        ({u:.0f}, {v:.0f}, {x:.3f}, {y:.3f}),")
    print("    ]")
    print("    H: Optional[np.ndarray] = np.array([")
    for row in h:
        print("        [" + ", ".join(f"{c:+.8e}" for c in row) + "],")
    print("    ], dtype=np.float64)")
    print(f"    U_RANGE: Tuple[float, float] = ({min(us):.0f}, {max(us):.0f})")
    print(f"    V_RANGE: Tuple[float, float] = ({min(vs):.0f}, {max(vs):.0f})")
    print("=" * 60 + "\n")


def calibrate(cv2, args):
    points = []
    if args.load and POINTS_FILE.exists():
        points = [tuple(p) for p in json.loads(POINTS_FILE.read_text(encoding="utf-8"))]
        print(f"已載入 {len(points)} 點: {POINTS_FILE}")

    cap = open_camera(cv2, args.index, args.warmup)
    state = {"frozen": None, "click": None}

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and state["frozen"] is not None:
            state["click"] = (float(x), float(y))

    cv2.namedWindow(WINDOW)
    cv2.setMouseCallback(WINDOW, on_mouse)
    print("SPACE 凍結畫面 → 點標記中心 → 終端機輸入 X,Y；ENTER 計算；ESC 結束")

    try:
        while True:
            if state["frozen"] is None:
                ok, frame = cap.read()
                if not ok:
                    print("✗ 讀取畫面失敗")
                    break
            else:
                frame = state["frozen"].copy()

            draw_points(cv2, frame, points)
            label = "FROZEN - click marker" if state["frozen"] is not None else "LIVE - SPACE to freeze"
            cv2.putText(frame, f"{label}  points={len(points)}", (10, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)
            cv2.imshow(WINDOW, frame)
            key = cv2.waitKey(30) & 0xFF

            if state["click"] is not None:
                u, v = state["click"]
                state["click"] = None
                xy = ask_xy(u, v)
                if xy:
                    points.append((u, v, xy[0], xy[1]))
                    save_points(points)
                    print(f"  ✓ 第 {len(points)} 點 ({u:.0f},{v:.0f}) → ({xy[0]:.1f},{xy[1]:.1f})")

            if key in (27, ord("q")):
                break
            if key == ord(" "):
                state["frozen"] = None if state["frozen"] is not None else frame.copy()
            elif key == ord("u") and points:
                print(f"  刪掉第 {len(points)} 點 {points.pop()}")
                save_points(points)
            elif key in (13, 10):
                if len(points) < 4:
                    print(f"  至少要 4 點，目前 {len(points)} 點")
                else:
                    report(points)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        if points:
            save_points(points)
            print(f"點已存到 {POINTS_FILE}")


def check(cv2, args):
    """標定貼回去之後：即時量切割區的小黃瓜，畫出兩端、頂點與預計下刀起點"""
    from config_phase import ChopPlanConfig
    from vision_skeleton import VisionSystem

    if not ChopZoneHomography.is_calibrated():
        sys.exit("✗ ChopZoneHomography 還沒有 H，先標定並貼回 src/config_vision.py")

    vision = VisionSystem()
    cap = open_camera(cv2, args.index, args.warmup)
    print("SPACE 量一次；ESC 結束")
    shown = None
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            cv2.imshow(WINDOW, shown if shown is not None else frame)
            key = cv2.waitKey(30) & 0xFF
            if key in (27, ord("q")):
                break
            if key != ord(" "):
                continue

            result, reason = vision.measure_in_chop_zone(args.food, frame)
            shown = frame.copy()
            if result is None:
                print(f"✗ {reason}")
                continue
            xs = sorted(p[0] for p in result["ends_mm"])
            plan, note = ChopPlanConfig.plan(xs[0], xs[1])
            print(f"長 {result['length_mm']:.0f}mm  偏角 {result['axis_angle_deg']:.1f}°  "
                  f"兩端 X={xs[0]:.1f}～{xs[1]:.1f}  → {note}")
            u, v = result["center_pixel"]
            text = (f"L={result['length_mm']:.0f}mm start={plan['start']} cuts={plan['cuts']}"
                    if plan else f"L={result['length_mm']:.0f}mm NG")
            cv2.putText(shown, text, (int(u) - 90, int(v) - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0) if plan else (0, 0, 255), 2)
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", type=int, default=VisionProcessingConfig.CAMERA_INDEX)
    ap.add_argument("--warmup", type=int, default=VisionProcessingConfig.CAMERA_WARMUP_FRAMES)
    ap.add_argument("--load", action="store_true", help="從上次存的點繼續")
    ap.add_argument("--check", action="store_true", help="標定後即時檢查量測結果")
    ap.add_argument("--food", default="CUCUMBER", type=str.upper, help="--check 量哪種食材（CUCUMBER / CARROT）")
    args = ap.parse_args()

    import cv2
    if args.check:
        check(cv2, args)
    else:
        calibrate(cv2, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
