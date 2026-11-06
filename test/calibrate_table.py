"""
SmartCook 檯面標定工具 (Table Calibration)

相機被動過之後，config_vision.TableHomography 那組 H 就失效了（取料位置會整片偏掉），
用這支重新標定。做法跟 2026-09-02 那次一樣：手臂走 3×3 網格（相對 pickup_origin
的偏移 x = +100 / 0 / -100、y = 0 / 100 / 200 mm），每格量一次像素座標。

標定步驟（每一格）:
    1. 用教導器把手臂移到 pickup_origin + (x, y)，把食材（或小標記）放在夾爪正下方
    2. 手臂退開到不擋畫面的位置
    3. 預覽視窗按 SPACE 拍照：
         - 畫面上只有一個 YOLO 偵測 → 自動取它的中心點
         - 偵測不到或不只一個 → 用滑鼠點食材/標記中心
       ENTER 確認、r 重拍、s 跳過這格
    4. 9 格做完自動計算；也可以中途按 c 先算
    5. 終端機印出殘差、留一驗證、跟舊標定比偏了多少，以及一段程式碼，
       貼回 src/config_vision.py 的 TableHomography

用法:
    python calibrate_table.py               # 標定（預設攝影機 index 0）
    python calibrate_table.py --load        # 從上次存的點繼續（captures/table_points.json）
    python calibrate_table.py --report      # 不開相機，只用存檔的點計算
    python calibrate_table.py --grid "100,0,-100" "0,100,200"   # 自訂網格（x 清單、y 清單）

預覽視窗操作:
    SPACE   拍照（偵測 / 等你點）
    滑鼠左鍵 手動指定中心點（拍照後）
    ENTER   確認這格
    r       重拍      s  跳過這格      u  刪掉上一格
    c       用目前的點先計算      ESC / q 結束（已量的點會存檔）
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from config_vision import TableHomography, VisionProcessingConfig

POINTS_FILE = Path(__file__).resolve().parent / "captures" / "table_points.json"
WINDOW = "table calibration"


def save_points(points):
    POINTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    POINTS_FILE.write_text(json.dumps(points, ensure_ascii=False, indent=1), encoding="utf-8")


def load_points():
    if not POINTS_FILE.exists():
        return []
    return [tuple(p) for p in json.loads(POINTS_FILE.read_text(encoding="utf-8"))]


class _Fit(TableHomography):
    """拿來算新 H 的暫存類別，不動到原本的 TableHomography"""


def report(points):
    """解單應性、印殘差 / 留一驗證 / 跟舊標定的偏移，以及要貼回去的程式碼"""
    if len(points) < 4:
        print(f"✗ 至少要 4 點，目前 {len(points)} 點")
        return

    _Fit.H = _Fit.solve(points)
    print("\n逐點殘差（新標定）與舊標定的偏移:")
    print("  像素 (u,v)    手臂 (x,y)     新H算出          誤差    舊H算出（偏移）")
    errs = []
    for u, v, x, y, px, py, err in _Fit.residuals(points):
        errs.append(err)
        ox, oy = TableHomography.pixel_to_mm(u, v)
        print(f"  ({u:3.0f},{v:3.0f})   ({x:5.0f},{y:4.0f})   ({px:7.1f},{py:6.1f})  {err:5.2f}mm"
              f"   ({ox:7.1f},{oy:6.1f})  {np.hypot(ox - x, oy - y):5.1f}mm")
    rms = float(np.sqrt(np.mean(np.square(errs))))
    print(f"新標定 RMS {rms:.2f}mm，最大 {max(errs):.2f}mm")

    if len(points) >= 5:
        loo = []
        for i in range(len(points)):
            rest = points[:i] + points[i + 1:]
            _Fit.H = _Fit.solve(rest)
            u, v, x, y = points[i]
            px, py = _Fit.pixel_to_mm(u, v)
            loo.append(float(np.hypot(px - x, py - y)))
        _Fit.H = _Fit.solve(points)
        worst = int(np.argmax(loo))
        print(f"留一驗證 平均 {np.mean(loo):.2f}mm、最大 {max(loo):.2f}mm"
              f"（第 {worst + 1} 點 {points[worst][2]:.0f},{points[worst][3]:.0f}）")
        if max(loo) > 15:
            print("⚠️ 有一點留一誤差超過 15mm，可能量偏了，建議用 --load 刪掉重量")
    if max(errs) > 10:
        print("⚠️ 最大殘差超過 10mm，建議檢查離群的那幾點重測")

    us = [p[0] for p in points]
    vs = [p[1] for p in points]
    print("\n===== 貼回 src/config_vision.py 的 TableHomography =====")
    print("    CALIBRATION_POINTS = [")
    for u, v, x, y in points:
        print(f"        ({u:.0f}, {v:.0f}, {x:4.0f}, {y:4.0f}),")
    print("    ]")
    print("    H = np.array([")
    for row in _Fit.H:
        print("        [" + ", ".join(f"{c:+.8e}" for c in row) + "],")
    print("    ], dtype=np.float64)")
    print(f"    RMS_ERROR_MM = {rms:.2f}")
    print(f"    MAX_ERROR_MM = {max(errs):.2f}")
    print(f"    U_RANGE = ({min(us):.0f}, {max(us):.0f})")
    print(f"    V_RANGE = ({min(vs):.0f}, {max(vs):.0f})")
    print("=" * 60 + "\n")


def calibrate(cv2, args, grid):
    from calibrate_chop_zone import draw_points, open_camera
    from vision_skeleton import YOLODetector

    points = load_points() if args.load else []
    if points:
        print(f"已載入 {len(points)} 點: {POINTS_FILE}")
    done = {(p[2], p[3]) for p in points}
    todo = [g for g in grid if g not in done]

    detector = YOLODetector()
    cap = open_camera(cv2, args.index, args.warmup)
    state = {"frozen": None, "pick": None}

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and state["frozen"] is not None:
            state["pick"] = (float(x), float(y))
            print(f"  手動指定 ({x},{y})")

    cv2.namedWindow(WINDOW)
    cv2.setMouseCallback(WINDOW, on_mouse)

    def announce():
        if todo:
            x, y = todo[0]
            print(f"\n▶ 第 {len(points) + 1} 點：手臂移到 pickup_origin + ({x:.0f}, {y:.0f}) mm，"
                  f"食材放在夾爪下、手臂退開，按 SPACE")

    announce()
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
            if state["pick"] is not None:
                u, v = state["pick"]
                cv2.drawMarker(frame, (int(u), int(v)), (0, 255, 0), cv2.MARKER_CROSS, 20, 2)
            target = f"target ({todo[0][0]:.0f},{todo[0][1]:.0f})" if todo else "grid done - c to compute"
            mode = "FROZEN  ENTER ok / r retake / click" if state["frozen"] is not None else "LIVE  SPACE capture"
            cv2.putText(frame, f"{target}  {mode}", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            cv2.imshow(WINDOW, frame)
            key = cv2.waitKey(30) & 0xFF

            if key in (27, ord("q")):
                break
            if key == ord("c"):
                report(points)
            elif key == ord("u") and points:
                p = points.pop()
                todo.insert(0, (p[2], p[3]))
                save_points(points)
                print(f"  刪掉上一點 {p}")
                announce()
            elif key == ord("s") and todo:
                print(f"  跳過 {todo.pop(0)}")
                state["frozen"], state["pick"] = None, None
                announce()
            elif key == ord("r"):
                state["frozen"], state["pick"] = None, None
            elif key == ord(" ") and todo and state["frozen"] is None:
                state["frozen"] = frame.copy()
                dets = detector.detect(frame)
                if len(dets) == 1:
                    d = dets[0]
                    state["pick"] = (d["center_x_pixel"], d["center_y_pixel"])
                    print(f"  YOLO {d.get('class_name', '')} 中心 ({state['pick'][0]:.0f},{state['pick'][1]:.0f})"
                          f"，ENTER 確認 / 點滑鼠改位置 / r 重拍")
                else:
                    state["pick"] = None
                    print(f"  偵測到 {len(dets)} 個物件，請用滑鼠點食材中心，再按 ENTER")
            elif key in (13, 10) and state["frozen"] is not None:
                if state["pick"] is None:
                    print("  還沒有中心點：用滑鼠點一下")
                    continue
                x, y = todo.pop(0)
                u, v = state["pick"]
                points.append((round(u, 1), round(v, 1), x, y))
                save_points(points)
                print(f"  ✓ ({u:.0f},{v:.0f}) → ({x:.0f},{y:.0f})")
                state["frozen"], state["pick"] = None, None
                if todo:
                    announce()
                else:
                    report(points)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        if points:
            save_points(points)
            print(f"點已存到 {POINTS_FILE}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", type=int, default=VisionProcessingConfig.CAMERA_INDEX)
    ap.add_argument("--warmup", type=int, default=VisionProcessingConfig.CAMERA_WARMUP_FRAMES)
    ap.add_argument("--load", action="store_true", help="從上次存的點繼續")
    ap.add_argument("--report", action="store_true", help="不開相機，只用存檔的點計算")
    ap.add_argument("--grid", nargs=2, metavar=("XS", "YS"), default=("100,0,-100", "0,100,200"),
                    help="網格的 x 清單與 y 清單（mm，相對 pickup_origin）")
    args = ap.parse_args()

    xs = [float(t) for t in args.grid[0].split(",")]
    ys = [float(t) for t in args.grid[1].split(",")]
    grid = [(x, y) for y in ys for x in xs]

    if args.report:
        report(load_points())
        return 0

    import cv2
    calibrate(cv2, args, grid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
