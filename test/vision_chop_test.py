#!/usr/bin/env python3
"""
SmartCook 視覺量測測試（不連手臂、不設任何限制）

拍一張照（或讀一張存好的圖），YOLO 偵測所有食材，印出每個偵測的原始數值：
像素中心、OBB 長寬、角度、長軸兩端點，用取料區的檯面單應性粗估成 mm，
再換算「整根切完要幾刀」。所有數字照實印出，不做上下限檢查，
用來先看視覺量出來的值合不合理，再決定刀數上限等參數。

用法:
    python vision_chop_test.py                          # 用相機拍一張
    python vision_chop_test.py --repeat 5               # 連拍 5 張，看數值穩不穩
    python vision_chop_test.py --image captures/yolo_070.jpg
    python vision_chop_test.py --food CUCUMBER --save   # 只看小黃瓜，存標註圖

⚠️ mm 是用取料區的 TableHomography 換算的：
   - 座標是相對 pickup_origin 的偏移，不是左臂座標，不能直接跟 chop_1[] 比位置
   - 切割區如果不在取料區標定範圍內，是外推值，誤差可能很大（會標 ⚠️外推）
   - 長度只用到比例尺，比位置可靠，但仍只是粗估
"""

import argparse
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import cv2  # noqa: E402

from config_phase import CHOP_STEP_MM, ChopPlanConfig  # noqa: E402
from config_vision import ChopZoneHomography, TableHomography  # noqa: E402
from vision_skeleton import VisionSystem  # noqa: E402

CAPTURE_DIR = ROOT / "test" / "captures"


def long_axis_endpoints(d: Dict) -> Tuple[Tuple[float, float], Tuple[float, float], float]:
    """
    OBB 長軸的兩個端點（像素）與長軸長度

    OBB 的 angle_deg 是寬邊 (width) 的方向；高比寬長時長軸要轉 90°。
    非 OBB 模型 (angle_source='estimated') 的框是軸對齊的，angle 只有 0/90 的粗估。
    色彩精算過的 angle (color_head_tail) 是頭尾方向，本身就沿長軸。
    """
    w, h = d["width_pixel"], d["height_pixel"]
    length = max(w, h)
    if d["angle_source"] == "color_head_tail":
        theta = math.radians(d["angle_deg"])
    elif d["angle_source"] == "obb":
        theta = math.radians(d["angle_deg"] + (90.0 if h > w else 0.0))
    else:  # estimated：軸對齊框
        theta = math.radians(90.0 if h > w else 0.0)
    dx, dy = math.cos(theta) * length / 2, math.sin(theta) * length / 2
    cx, cy = d["center_x_pixel"], d["center_y_pixel"]
    return (cx - dx, cy - dy), (cx + dx, cy + dy), length


def measure(d: Dict) -> Dict:
    p1, p2, length_px = long_axis_endpoints(d)
    m1, m2 = TableHomography.pixel_to_mm(*p1), TableHomography.pixel_to_mm(*p2)
    length_mm = math.hypot(m2[0] - m1[0], m2[1] - m1[1])
    in_area = all(TableHomography.is_within_calibrated_area(*p) for p in (p1, p2))
    return {
        "p1": p1, "p2": p2, "length_px": length_px,
        "m1": m1, "m2": m2, "length_mm": length_mm,
        "mm_per_px": length_mm / length_px if length_px else float("nan"),
        "cuts": length_mm / CHOP_STEP_MM,
        "in_area": in_area,
    }


def print_detection(i: int, d: Dict, m: Dict):
    flag = "" if m["in_area"] else "  ⚠️外推（端點超出取料區標定範圍）"
    print(f"\n  [{i}] {d['class_name']}  信心度 {d['confidence']:.2f}{flag}")
    print(f"      像素中心 ({d['center_x_pixel']:.1f}, {d['center_y_pixel']:.1f})  "
          f"框 寬 {d['width_pixel']:.1f} × 高 {d['height_pixel']:.1f} px  "
          f"角度 {d['angle_deg']:.1f}° ({d['angle_source']})")
    print(f"      長軸端點 px  ({m['p1'][0]:.1f}, {m['p1'][1]:.1f}) ～ ({m['p2'][0]:.1f}, {m['p2'][1]:.1f})  "
          f"長 {m['length_px']:.1f} px")
    print(f"      長軸端點 mm  ({m['m1'][0]:.1f}, {m['m1'][1]:.1f}) ～ ({m['m2'][0]:.1f}, {m['m2'][1]:.1f})  "
          f"長 {m['length_mm']:.1f} mm  （{m['mm_per_px']:.3f} mm/px）")
    print(f"      整根以 {CHOP_STEP_MM:g}mm 一刀 → {m['cuts']:.1f} 刀"
          f"（無條件捨去 {math.floor(m['cuts'])}、四捨五入 {round(m['cuts'])}）")


def annotate(image, items: List[Tuple[Dict, Dict]]):
    out = image.copy()
    for d, m in items:
        color = (0, 200, 0) if m["in_area"] else (0, 0, 255)
        p1 = tuple(int(round(v)) for v in m["p1"])
        p2 = tuple(int(round(v)) for v in m["p2"])
        cv2.line(out, p1, p2, color, 2)
        cv2.circle(out, p1, 4, color, -1)
        cv2.circle(out, p2, 4, color, -1)
        label = f"{d['class_name']} {m['length_mm']:.0f}mm {m['cuts']:.0f}cut"
        cv2.putText(out, label, (p1[0], max(p1[1] - 8, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    u0, u1 = TableHomography.U_RANGE
    v0, v1 = TableHomography.V_RANGE
    cv2.rectangle(out, (u0, v0), (u1, v1), (255, 200, 0), 1)   # 取料區標定範圍
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", help="讀存好的圖片，不開相機")
    ap.add_argument("--repeat", type=int, default=1, help="相機連拍幾張（--image 時忽略）")
    ap.add_argument("--food", type=str.upper, help="只看這個類別，例如 CUCUMBER / CARROT / LETTUCE")
    ap.add_argument("--save", action="store_true", help=f"把標註圖存到 {CAPTURE_DIR.relative_to(ROOT)}")
    args = ap.parse_args()

    vision = VisionSystem()
    if vision.yolo_detector.model is None:
        print("✗ YOLO 模型沒有載入，看上面的警告訊息")
        return 1

    shots = 1 if args.image else max(args.repeat, 1)
    history: Dict[str, List[float]] = {}

    for shot in range(1, shots + 1):
        if args.image:
            image = cv2.imread(args.image)
            if image is None:
                print(f"✗ 讀不到圖片: {args.image}")
                return 1
            source = args.image
        else:
            image = vision.capture_frame()
            if image is None:
                print("✗ 相機拍照失敗")
                return 1
            source = f"相機 第 {shot}/{shots} 張"

        detections = vision.yolo_detector.detect(image)
        if args.food:
            detections = [d for d in detections if d["class_name"] == args.food]

        print(f"\n=== {source}：{len(detections)} 個偵測 "
              f"（影像 {image.shape[1]}×{image.shape[0]}）===")
        items = []
        for i, d in enumerate(detections, 1):
            m = measure(d)
            items.append((d, m))
            print_detection(i, d, m)
            history.setdefault(d["class_name"], []).append(m["length_mm"])

        # 切割區標定好之後，再用正式流程的量測（左臂座標）算一次起始格與刀數
        if ChopZoneHomography.is_calibrated():
            for food in sorted({d["class_name"] for d in detections} & {"CUCUMBER", "CARROT"}):
                r, why = vision.measure_in_chop_zone(food, image)
                if r is None:
                    print(f"\n  [切割區量測] {food}: ✗ {why}")
                    continue
                xs = sorted(p[0] for p in r["ends_mm"])
                plan, note = ChopPlanConfig.plan(xs[0], xs[1])
                print(f"\n  [切割區量測] {food}: 長 {r['length_mm']:.1f}mm  偏角 {r['axis_angle_deg']:.1f}°  "
                      f"左臂 X {xs[0]:.1f}～{xs[1]:.1f}（端點來源 {r['source']}）")
                print(f"      → {note}")
                history.setdefault(f"{food}(切割區)", []).append(r["length_mm"])
        elif shot == 1:
            print("\n  （切割區還沒標定，只有上面用取料區粗估的 mm；"
                  "標定方式見 test/calibrate_chop_zone.py）")

        if args.save:
            CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
            path = CAPTURE_DIR / datetime.now().strftime(f"vision_chop_%Y%m%d_%H%M%S_{shot}.jpg")
            cv2.imwrite(str(path), annotate(image, items))
            print(f"\n  標註圖: {path}")

    if shots > 1 and history:
        print("\n=== 連拍統計（長度 mm）===")
        for name, vals in history.items():
            print(f"  {name}: {len(vals)} 筆  平均 {mean(vals):.1f}  "
                  f"最小 {min(vals):.1f}  最大 {max(vals):.1f}  差距 {max(vals) - min(vals):.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
