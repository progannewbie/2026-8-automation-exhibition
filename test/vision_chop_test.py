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

偏移（第 1 格相對左臂教點 cu）：
    切割區還沒標定時，用現場手動對點的經驗公式估（見 OFFSET_REFERENCE），
    印成「==> 偏移 .offset = +45.3 mm」這一行，只在小黃瓜頭尾方向跟對點時一致時給。
    切割區標定後改用正式量測（左臂座標）。

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


def suggested_offset(front_x: float) -> float:
    """讓第 1 格剛好落在「前端 + TIP_OFFSET_MM」的偏移量（相對 cu）"""
    return front_x + ChopPlanConfig.TIP_OFFSET_MM - ChopPlanConfig.CU_X_MM


def raw_range(front_x: float, back_x: float, offset: float) -> Tuple[int, int]:
    """不設上下限，照 ChopPlanConfig.plan 的算法回傳 (起始格, 最後一格)"""
    first_x = ChopPlanConfig.CU_X_MM + offset
    start = int(round((front_x + ChopPlanConfig.TIP_OFFSET_MM - first_x) / CHOP_STEP_MM)) + 1
    last = int((back_x - ChopPlanConfig.TAIL_MARGIN_MM - first_x) // CHOP_STEP_MM) + 1
    return start, last


def print_offset(food: str, r: Dict):
    """切割區量測結果 → 建議偏移、第一刀位置、刀數（不設上下限，超出 AS 範圍只標示）"""
    front, back = sorted(p[0] for p in r["ends_mm"])
    sug = suggested_offset(front)
    cur = ChopPlanConfig.CHOP_ORIGIN_OFFSET_MM
    print(f"\n  [切割區量測] {food}: 長 {r['length_mm']:.1f}mm  偏角 {r['axis_angle_deg']:.1f}°"
          f"（端點來源 {r['source']}）")
    if r["axis_angle_deg"] > ChopPlanConfig.MAX_AXIS_ANGLE_DEG:
        print(f"      ⚠️ 偏角超過 {ChopPlanConfig.MAX_AXIS_ANGLE_DEG:g}°：食材沒有順著刀子行進方向（左臂 X）擺，"
              f"正式流程會拒切；下面的 X 範圍比實際長度短")
    print(f"      左臂 X：前端 {front:.1f}  後端 {back:.1f}    cu = {ChopPlanConfig.CU_X_MM:.1f}")
    print(f"      前端距 cu：{front - ChopPlanConfig.CU_X_MM:+.1f} mm")
    for label, off in (("建議偏移", sug), ("目前設定", cur)):
        start, last = raw_range(front, back, off)
        cuts = last - start + 1
        first_x = ChopPlanConfig.CU_X_MM + off + (start - 1) * CHOP_STEP_MM
        ok = (1 <= cuts <= ChopPlanConfig.MAX_CUTS and start >= 1 and
              last <= ChopPlanConfig.MAX_INDEX and abs(off) <= 300)
        print(f"      {label} {off:+7.1f} mm → 第 {start}～{last} 格、{cuts} 刀，第一刀 X={first_x:.1f}"
              f"{'' if ok else '  ⚠️ 超出手臂允許範圍（60 刀 / 第 60 格 / ±300mm）'}")
    print(f"      手動驗證：python test/chop_points.py {food} --cuts 3 --offset {sug:.1f}"
          f"，教導器移到第 1 格看刀子是不是落在前端往內 {ChopPlanConfig.TIP_OFFSET_MM:g}mm")


# ----------------------------------------------------------------------------
# 切割區還沒標定時的偏移估算（經驗公式）
#
# 用教導器手動對點，記下「這個擺法要填的偏移」，對照同一張照片的視覺數值：
#   X：取料區座標「X 較大那端」每移 1mm，偏移就差 1mm（舊點位時三次驗證，誤差 ±0.3mm）
#   Y：取料區座標「X 較大那端（第一刀那端）的 Y」，方向與比例由 2 筆以上資料擬合
#      （小黃瓜擺放會斜，用中心 Y 會差到 30mm 以上，2026-10-05 第三筆對點時發現）
#
# 2026-10-05 點位重教後重新量：這個擺法定義為 (0, 0)。舊點位的資料已作廢。
#     (取料區右端 X, 確認的 CHOP_ORIGIN_OFFSET_MM)
OFFSET_REFERENCE: List[Tuple[float, float]] = [
    (314.6, 0.0),
    (314.4, 0.0),    # 同一個 (0, 0) 擺法再拍一次
    (237.1, -77.4),  # 第一刀 X 328.9、Y 625.88
    (248.2, -66.3),  # 第一刀 X 340.0（公式估的值，現場確認正確）
]
#     (取料區右端 Y, 確認的 CHOP_ORIGIN_OFFSET_Y_MM)；至少 2 筆才會估
OFFSET_Y_REFERENCE: List[Tuple[float, float]] = [
    (21.9, 0.0),     # (0, 0) 擺法兩次右端 Y 的平均（26.2、17.5），算同一個基準點
    (67.9, 53.0),    # 第一刀 Y 625.88（基準 572.925）
    (-11.8, -36.9),  # 第一刀 Y 535.977
    (10.3, -12.4),   # 第一刀 Y 560.5（公式估的值，現場確認正確）
]
# 只檢查小黃瓜是否沿畫面橫向擺（長軸 0°/180° 都算），不分頭尾：
# 色彩判斷的頭尾不可靠，同一個擺向會出現 6° 和 183°（2026-10-05 現場確認沒有放反）。
# 公式只用「取料區 X 較大那端」，跟頭尾無關。
REF_AXIS_DEG = 0.0
ANGLE_TOLERANCE_DEG = 30.0
# ⚠️ 相機、切割區或手臂點位動過就失效，要重新手動對點、更新上面兩組資料。
# ----------------------------------------------------------------------------

REF_K = mean(off - tab for tab, off in OFFSET_REFERENCE)
REF_SPREAD = max(abs(off - tab - REF_K) for tab, off in OFFSET_REFERENCE)


def fit_y() -> Optional[Tuple[float, float, float]]:
    """Y 偏移 = a × 右端 Y + b 的最小平方解，回傳 (a, b, 最大誤差)；資料不足回 None"""
    pts = OFFSET_Y_REFERENCE
    if len(pts) < 2:
        return None
    mx, my = mean(p[0] for p in pts), mean(p[1] for p in pts)
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    if sxx < 1e-6:
        return None   # 右端 Y 都一樣，分不出斜率
    a = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx
    b = my - a * mx
    return a, b, max(abs(a * p[0] + b - p[1]) for p in pts)


def estimate_offset(d: Dict, m: Dict) -> Tuple[Optional[float], str]:
    """
    用經驗公式估 X 偏移

    Returns:
        (偏移 mm, 說明)；偏移是 None 表示這次不能估，說明寫原因
    """
    axis = (d["angle_deg"] - REF_AXIS_DEG) % 180.0      # 長軸方向，不分頭尾
    diff = min(axis, 180.0 - axis)
    if diff > ANGLE_TOLERANCE_DEG:
        return None, (f"小黃瓜長軸斜了 {diff:.0f}°（上限 {ANGLE_TOLERANCE_DEG:.0f}°），"
                      f"公式只適用橫向擺放，請擺正")
    right_x = max(m["m1"][0], m["m2"][0])
    return right_x + REF_K, f"右端 X = {right_x:.1f}"


def print_offset_estimate(d: Dict, m: Dict) -> Optional[float]:
    off, note = estimate_offset(d, m)
    if off is None:
        print(f"\n  [偏移] ✗ {note}")
        return None
    warn = "  ⚠️ 超過 ±300mm，手臂會拒絕" if abs(off) > 300 else ""
    spread = f"對點資料誤差 ±{REF_SPREAD:.1f}mm" if len(OFFSET_REFERENCE) > 1 else "對點資料 1 筆"
    print(f"\n  ==> 偏移 .offset = {off:+.1f} mm（{note}，{spread}）{warn}")
    print(f"      目前 config_phase.ChopPlanConfig.CHOP_ORIGIN_OFFSET_MM = "
          f"{ChopPlanConfig.CHOP_ORIGIN_OFFSET_MM:+.1f}")

    right_y = max((m["m1"], m["m2"]), key=lambda p: p[0])[1]   # X 較大那端（第一刀那端）的 Y
    fit = fit_y()
    if fit is None:
        print(f"  ==> Y 偏移：還沒有足夠對點資料（目前 {len(OFFSET_Y_REFERENCE)} 筆，至少 2 筆）。"
              f"這次右端 Y = {right_y:.1f}，")
        print("      對點後把「右端 Y、確認的 Y 偏移」一起告訴我，加進 OFFSET_Y_REFERENCE")
    else:
        a, b, err = fit
        off_y = a * right_y + b
        warn = "  ⚠️ 超過 ±100mm，手臂會拒絕" if abs(off_y) > 100 else ""
        print(f"  ==> Y 偏移 .offset_y = {off_y:+.1f} mm（右端 Y = {right_y:.1f}，"
              f"對點資料誤差 ±{err:.1f}mm）{warn}")
    print(f"      目前 config_phase.ChopPlanConfig.CHOP_ORIGIN_OFFSET_Y_MM = "
          f"{ChopPlanConfig.CHOP_ORIGIN_OFFSET_Y_MM:+.1f}")
    return off


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

        # 切割區標定好之後，用正式流程的量測（左臂座標）算偏移與刀數
        if ChopZoneHomography.is_calibrated():
            for food in sorted({d["class_name"] for d in detections} & {"CUCUMBER", "CARROT"}):
                r, why = vision.measure_in_chop_zone(food, image)
                if r is None:
                    print(f"\n  [切割區量測] {food}: ✗ {why}")
                    continue
                print_offset(food, r)
                history.setdefault(f"{food}(切割區) 長度", []).append(r["length_mm"])
                history.setdefault(f"{food}(切割區) 建議偏移",
                                   []).append(suggested_offset(min(p[0] for p in r["ends_mm"])))
        else:
            # 只用信心度最高的那根小黃瓜算偏移（畫面邊緣常有別根或誤判）
            cucumbers = [(d, m) for d, m in items if d["class_name"] == "CUCUMBER"]
            if cucumbers:
                best = max(range(len(cucumbers)), key=lambda k: cucumbers[k][0]["confidence"])
                d, m = cucumbers[best]
                if len(cucumbers) > 1:
                    print(f"\n  （有 {len(cucumbers)} 根小黃瓜，偏移只用信心度最高的 "
                          f"{d['confidence']:.2f}，像素中心 ({d['center_x_pixel']:.0f}, "
                          f"{d['center_y_pixel']:.0f})）")
                off = print_offset_estimate(d, m)
                if off is not None:
                    history.setdefault("CUCUMBER 偏移", []).append(off)

        if args.save:
            CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
            path = CAPTURE_DIR / datetime.now().strftime(f"vision_chop_%Y%m%d_%H%M%S_{shot}.jpg")
            cv2.imwrite(str(path), annotate(image, items))
            print(f"\n  標註圖: {path}")

    if shots > 1 and history:
        print("\n=== 連拍統計（mm）===")
        for name, vals in history.items():
            print(f"  {name}: {len(vals)} 筆  平均 {mean(vals):.1f}  "
                  f"最小 {min(vals):.1f}  最大 {max(vals):.1f}  差距 {max(vals) - min(vals):.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
