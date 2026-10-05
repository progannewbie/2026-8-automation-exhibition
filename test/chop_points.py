#!/usr/bin/env python3
"""
SmartCook 切割點位預覽（不連手臂、不動手臂）

讀 robot/ 底下兩臂 GBK 程式裡的教點與常數，照目前 DO_CHOP / do_chop 的邏輯
算出每一刀左臂的下刀座標、右臂的壓點座標，印成表格。用教導器手動把手臂移到
這些點，看跟實際食材差多少，再回來微調參數。

    左臂第 i 格下刀點 = chop_1[1] 沿 X 往後 (i-1)×5mm（上方點再 +50mm）
    右臂第 i 格壓點   = press_chop_zone 沿右臂 X 移 (i-1)×5mm×press_dir，再往下壓 press_mm
                        （press_chop_zone 應教在離 chop_1[1] 下刀處 10mm、還沒切的那一側）

用法:
    python chop_points.py CUCUMBER                      # 小黃瓜，第 1 格起，刀數取 config_phase
    python chop_points.py CUCUMBER --cuts 41 --start 3  # 第 3～43 格
    python chop_points.py ROMAINE --start 17            # 生菜，預覽第 17 格那一刀
    python chop_points.py CUCUMBER --cuts 3 --actual chop_1 310.0 548.6 -297.0
                                                         # 手動量到的實際座標，算差距與建議值

⚠️ 座標是 repo 裡 .as 檔匯出當下的教點。控制器上如果重教過、還沒重新匯出，
   以控制器為準。
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from config_phase import CHOP_STEP_MM, FOOD_CUT_PARAMS, ChopPlanConfig  # noqa: E402

LEFT_AS = ROOT / "robot" / "F60_F_左臂_GBK.as"
RIGHT_AS = ROOT / "robot" / "F60_R_右臂_GBK.as"

FOODS = {"CUCUMBER": "小黃瓜", "CARROT": "紅蘿蔔", "ROMAINE": "羅曼生菜"}
LIFT_MM = 50.0   # DO_CHOP 裡 chop_now_per = chop_now 往 +Z 50mm

Pose = Tuple[float, float, float, float, float, float]   # X Y Z O A T


# ============================================================================
# 讀 AS 檔
# ============================================================================

def read_as(path: Path) -> str:
    return path.read_bytes().decode("gbk")


def read_trans(text: str) -> Dict[str, Pose]:
    """.TRANS 區段：每行「名稱 X Y Z O A T」"""
    m = re.search(r"^\.TRANS\r?\n(.*?)^\.END", text, re.S | re.M)
    if not m:
        sys.exit("✗ AS 檔裡找不到 .TRANS 區段")
    points = {}
    for line in m.group(1).splitlines():
        parts = line.split()
        if len(parts) == 7:
            points[parts[0]] = tuple(float(v) for v in parts[1:])
    return points


def read_program(text: str, name: str) -> str:
    m = re.search(rf"^\.PROGRAM {re.escape(name)}\(.*?^\.END", text, re.S | re.M | re.I)
    if not m:
        sys.exit(f"✗ AS 檔裡找不到程式 {name}")
    return m.group(0)


def read_const(text: str, name: str) -> Optional[float]:
    m = re.search(rf"^\s*{name}\s*=\s*([-\d.eE+]+)", read_program(text, "init_const"), re.M)
    return float(m.group(1)) if m else None


def read_press_mm(right_text: str) -> Dict[str, float]:
    """右臂 do_chop 的 SCASE：SVALUE "食材": press_mm = N"""
    prog = read_program(right_text, "do_chop")
    return {food: float(mm) for food, mm in
            re.findall(r'SVALUE\s+"(\w+)"\s*:\s*\r?\n\s*press_mm\s*=\s*([-\d.]+)', prog)}


def shift_x(p: Pose, dx: float, dz: float = 0.0) -> Pose:
    return (p[0] + dx, p[1], p[2] + dz) + p[3:]


# ============================================================================
# 主程式
# ============================================================================

def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("food", type=str.upper, choices=sorted(FOODS), help="食材")
    ap.add_argument("--cuts", type=int, help="刀數（預設取 config_phase.FOOD_CUT_PARAMS）")
    ap.add_argument("--start", type=int, help="從第幾格開始切（預設 1；ROMAINE 預設取 "
                                               "ChopPlanConfig.ROMAINE_START_INDEX）")
    ap.add_argument("--actual", nargs=4, action="append", metavar=("點名", "X", "Y", "Z"),
                    help="手動量到的實際座標，點名是 chop_<格> / press_<格>（例如 chop_1、press_1），可重複")
    args = ap.parse_args()

    left_text, right_text = read_as(LEFT_AS), read_as(RIGHT_AS)
    left_trans, right_trans = read_trans(left_text), read_trans(right_text)
    for name, table in (("chop_1[1]", left_trans), ("press_chop_zone", right_trans)):
        if name not in table:
            sys.exit(f"✗ 教點 {name} 不存在（.TRANS 裡沒有）")

    food = args.food
    cuts = args.cuts or FOOD_CUT_PARAMS[food].num_cuts
    start = args.start
    if start is None:
        start = ChopPlanConfig.ROMAINE_START_INDEX if food == "ROMAINE" else 1
        if start is None:
            print("✗ 生菜下刀位置 ChopPlanConfig.ROMAINE_START_INDEX 還沒設定，"
                  "用 --start 指定一格來預覽，例如 --start 17")
            return 1
    last = start + cuts - 1
    if not (1 <= cuts <= ChopPlanConfig.MAX_CUTS and start >= 1 and last <= ChopPlanConfig.MAX_INDEX):
        print(f"✗ 第 {start}～{last} 格、{cuts} 刀超出 AS 端允許範圍"
              f"（刀數 1～{ChopPlanConfig.MAX_CUTS}、最後一格 ≤ {ChopPlanConfig.MAX_INDEX}），"
              f"手臂會回 ERROR,E4005")
        return 1

    press_table = read_press_mm(right_text)
    if food not in press_table:
        print(f"✗ 右臂 do_chop 沒有 {food} 的 press_mm，手臂會回 ERROR,E4005")
        return 1
    press_mm = press_table[food]
    press_dir = read_const(right_text, "press_dir")
    ready = read_const(right_text, "press_follow_ready")

    print(f"{FOODS[food]} ({food})：第 {start}～{last} 格，共 {cuts} 刀")
    print(f"右臂 press_mm = {press_mm:g}，press_dir = {press_dir:g}，press_follow_ready = {ready:g}")
    if ready != 1:
        print("⚠️ 右臂 press_follow_ready 還是 0：press_chop_zone 重教在離 chop_1[1] 下刀處 10mm、"
              "確認方向後改成 1，否則手臂拒絕切割。下面右臂座標是用目前的 press_chop_zone 算的。")
    print(f"教點來源: {LEFT_AS.name} / {RIGHT_AS.name}（.TRANS 區段，單位 mm / deg）")

    c1 = left_trans["chop_1[1]"]
    p0 = right_trans["press_chop_zone"]
    print(f"\n左臂姿態每刀相同: O={c1[3]:.3f}  A={c1[4]:.3f}  T={c1[5]:.3f}")
    print(f"右臂姿態每刀相同: O={p0[3]:.3f}  A={p0[4]:.3f}  T={p0[5]:.3f}")

    print(f"\n  {'格':>3} {'左臂下刀 X':>11}{'Y':>10}{'下刀 Z':>10}{'上方 Z':>10}   │"
          f" {'右臂壓點 X':>11}{'Y':>10}{'上方 Z':>10}{'壓下 Z':>10}  備註")
    lookup: Dict[str, Pose] = {}
    for i in range(start, last + 1):
        cut = shift_x(c1, (i - 1) * CHOP_STEP_MM)
        press_up = shift_x(p0, (i - 1) * CHOP_STEP_MM * press_dir)
        press_down = shift_x(press_up, 0.0, -press_mm)
        lookup[f"chop_{i}"], lookup[f"press_{i}"] = cut, press_down
        note = "超出教點陣列 chop_1[1..30]，AS 即時計算" if i > 30 else ""
        print(f"  {i:>3} {cut[0]:11.3f}{cut[1]:10.3f}{cut[2]:10.3f}{cut[2] + LIFT_MM:10.3f}   │"
              f" {press_up[0]:11.3f}{press_up[1]:10.3f}{press_up[2]:10.3f}{press_down[2]:10.3f}  {note}")

    first, lastx = ChopPlanConfig.cut_x(start), ChopPlanConfig.cut_x(last)
    print(f"\n左臂下刀範圍 X {first:.1f} ～ {lastx:.1f}（跨距 {lastx - first:.0f}mm，每刀 {CHOP_STEP_MM:g}mm）")

    if args.actual:
        print("\n實際量測比對（實際 − 程式）")
        for name, *xyz in args.actual:
            if name not in lookup:
                print(f"  ✗ {name}: 這次沒有這個點，可用 chop_{start}～chop_{last}、press_{start}～press_{last}")
                continue
            ax, ay, az = (float(v) for v in xyz)
            px, py, pz = lookup[name][:3]
            dx, dy, dz = ax - px, ay - py, az - pz
            print(f"  {name}: ΔX={dx:+.2f}  ΔY={dy:+.2f}  ΔZ={dz:+.2f} mm")
            if name.startswith("chop_"):
                print("    → 左臂每格都是 chop_1[1] 往後算的：整排平移要重教 chop_1[1]"
                      "（並更新 ChopPlanConfig.CHOP_1_FIRST_X_MM）")
                if food == "ROMAINE" and abs(dx) >= CHOP_STEP_MM / 2:
                    print(f"    → 只是生菜下刀位置偏的話，ROMAINE_START_INDEX 改成 "
                          f"{start + round(dx / CHOP_STEP_MM)}")
            else:
                print(f"    → 壓的深度：press_mm 建議改成 {press_mm - dz:.1f}（右臂 do_chop 的 {food} 分支）")
                if abs(dx) > 1 or abs(dy) > 1:
                    print("    → X/Y 偏差：重教 press_chop_zone（離 chop_1[1] 下刀處 10mm）；"
                          "越切越偏的話檢查 press_dir")
    return 0


if __name__ == "__main__":
    sys.exit(main())
