#!/usr/bin/env python3
"""
視覺座標驗證 — 只跑偵測與座標轉換，不動手臂

用途：在接上完整流程之前，先確認 YOLO 偵測到的像素座標經過
TableHomography 換算出來的 mm，跟實際用尺量的偏移量對得上。

手臂座標是「相對 pickup_origin 的偏移量」，也就是 AS 端：
    POINT target_pt = TRANS(x_mm, y_mm, 0, 0, 0, 0) + pickup_origin

所以驗證方式是：把食材放在取料區，量它離 pickup_origin 教點多遠，
跟本程式印出來的 (x_mm, y_mm) 對照。

用法:
    python test_vision_coord.py                 # 拍一張，印出所有偵測結果
    python test_vision_coord.py --loop          # 連續拍，邊移動食材邊看數字變化
    python test_vision_coord.py --food CUCUMBER # 只看指定食材
    python test_vision_coord.py --image a.jpg   # 用現成圖片，不開相機
    python test_vision_coord.py --check-calib   # 只驗標定矩陣，不需要相機
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np


def print_calibration():
    """把標定資料與逐點殘差印出來，不需要相機"""
    from config_vision import TableHomography as T

    print("=" * 68)
    print("檯面單應性標定")
    print("=" * 68)
    print(f"標定點數 : {len(T.CALIBRATION_POINTS)}")
    print(f"像素範圍 : u {T.U_RANGE}  v {T.V_RANGE}")
    print(f"擬合殘差 : RMS {T.RMS_ERROR_MM} mm、最大 {T.MAX_ERROR_MM} mm")
    print("           （這是擬合殘差，不是新點的實際精度；留一交叉驗證約 3.7mm，")
    print("             真實精度落在兩者之間，要再收斂得增加標定點）")
    print()
    print("  像素 (u,v)      標定值 (mm)        推算 (mm)         誤差")
    print("  " + "-" * 60)
    errs = []
    for u, v, x, y, px, py, e in T.residuals():
        errs.append(e)
        print(f"  ({u:3.0f},{v:3.0f})      ({x:6.0f},{y:5.0f})     "
              f"({px:7.2f},{py:7.2f})   {e:5.2f} mm")
    print("  " + "-" * 60)
    print(f"  RMS {np.sqrt(np.mean(np.square(errs))):.2f} mm、最大 {max(errs):.2f} mm")
    print()


def describe(det, T):
    """把一筆偵測結果排成一行"""
    u, v = det['center_x_pixel'], det['center_y_pixel']
    x, y = det['center_x_mm'], det['center_y_mm']
    inside = T.is_within_calibrated_area(u, v)
    flag = "" if inside else "  ⚠️ 超出標定範圍，座標是外推值"
    return (f"  {det['class_name']:9s} "
            f"px({u:6.1f},{v:6.1f}) → ({x:8.2f},{y:8.2f}) mm   "
            f"角度 {det.get('angle_deg', 0):6.1f}° [{det.get('angle_source','?')}]"
            f"{flag}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--loop", action="store_true", help="連續偵測，Ctrl+C 結束")
    ap.add_argument("--interval", type=float, default=1.5, help="連續模式的間隔秒數")
    ap.add_argument("--food", help="只顯示指定食材 (CUCUMBER/CARROT/ROMAINE)")
    ap.add_argument("--image", help="改用現成圖片檔，不開相機")
    ap.add_argument("--check-calib", action="store_true", help="只印標定資料就結束")
    args = ap.parse_args()

    from config_vision import TableHomography as T

    print_calibration()
    if args.check_calib:
        return 0

    import cv2
    from vision_skeleton import VisionSystem

    vs = VisionSystem()
    if vs.yolo_detector.model is None:
        print("✗ YOLO 模型沒載入，無法偵測")
        return 1

    def one_shot() -> int:
        if args.image:
            image = cv2.imread(args.image)
            if image is None:
                print(f"✗ 讀不到圖片: {args.image}")
                return 1
        else:
            image = vs.capture_frame()
            if image is None:
                print("✗ 拍照失敗（相機可能被佔用，或 CAMERA_INDEX 設錯）")
                return 1

        dets = vs.detect_foods(image)
        if args.food:
            dets = [d for d in dets if d['class_name'] == args.food.upper()]

        ts = time.strftime("%H:%M:%S")
        if not dets:
            print(f"[{ts}] 沒有偵測到{'　' + args.food if args.food else '任何食材'}")
        else:
            print(f"[{ts}] 偵測到 {len(dets)} 個")
            for d in dets:
                print(describe(d, T))
        return 0

    if not args.loop:
        rc = one_shot()
        print("\n請用尺量食材中心離 pickup_origin 教點的偏移量，跟上面的 mm 對照。")
        print("對得上就可以接完整流程；差很多的話先確認 pickup_origin 有沒有教對。")
        return rc

    print("連續模式，移動食材觀察數字變化，Ctrl+C 結束\n")
    try:
        while True:
            one_shot()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n結束")
    return 0


if __name__ == "__main__":
    sys.exit(main())
