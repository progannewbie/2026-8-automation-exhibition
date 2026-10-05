#!/usr/bin/env python3
"""
SmartCook 切割點位預覽（不連手臂、不動手臂）

讀 robot/ 底下兩臂 GBK 程式裡存的教點，照目前 DO_CHOP / do_chop 的邏輯
算出每一刀的下刀座標與右臂壓點，印成表格。用教導器手動把手臂移到這些點，
看跟實際食材差多少，再回來微調參數。

用法:
    python chop_points.py CUCUMBER                 # 小黃瓜（刀數預設取 config_phase）
    python chop_points.py CARROT --cuts 5          # 指定刀數
    python chop_points.py ROMAINE --rom-mid 80     # 生菜，預覽 rom_mid_mm = 80 的下刀點
    python chop_points.py ROMAINE --rom-mid 80 --actual rom_cut 392.5 549.0 -296.0
                                                    # 手動量到的實際座標，算差距與建議值

⚠️ 座標是 repo 裡 .as 檔匯出當下的教點。控制器上如果重教過、還沒重新匯出，
   以控制器為準。
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from config_phase import FOOD_CUT_PARAMS  # noqa: E402

LEFT_AS = ROOT / "robot" / "F60_F_左臂_GBK.as"
RIGHT_AS = ROOT / "robot" / "F60_R_右臂_GBK.as"

FOODS = {"CUCUMBER": "小黃瓜", "CARROT": "紅蘿蔔", "ROMAINE": "羅曼生菜"}
LIFT_MM = 50.0   # DO_CHOP 裡 rom_per = rom_cut 往 +Z 50mm（同 chop_per 與 chop_1 的高度差）

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


def read_rom_mid(left_text: str) -> Optional[float]:
    """左臂 INIT_CONST 裡的 rom_mid_mm"""
    m = re.search(r"^\s*rom_mid_mm\s*=\s*([-\d.eE+]+)", read_program(left_text, "INIT_CONST"), re.M)
    return float(m.group(1)) if m else None


def read_press_mm(right_text: str) -> Dict[str, float]:
    """右臂 do_chop 的 SCASE：SVALUE "食材": press_mm = N"""
    prog = read_program(right_text, "do_chop")
    return {food: float(mm) for food, mm in
            re.findall(r'SVALUE\s+"(\w+)"\s*:\s*\r?\n\s*press_mm\s*=\s*([-\d.]+)', prog)}


# ============================================================================
# 照 DO_CHOP 的邏輯排出點位
# ============================================================================

# 一刀 = (刀號, 下刀點名, 下刀座標, 上方點名, 上方座標, 備註)
Cut = Tuple[str, str, Pose, str, Pose, str]


def left_cuts(food: str, cuts: int, trans: Dict[str, Pose],
              rom_mid: Optional[float]) -> List[Cut]:
    """照左臂 DO_CHOP 實際走的順序排出每一刀（每刀都是 上方 → 下刀 → 上方）"""
    def pt(name: str) -> Pose:
        if name not in trans:
            sys.exit(f"✗ 左臂教點 {name} 不存在（.TRANS 裡沒有）")
        return trans[name]

    if food == "ROMAINE":
        base = pt("chop_1[1]")
        cut = (base[0] + rom_mid,) + base[1:]
        per = cut[:2] + (cut[2] + LIFT_MM,) + cut[3:]
        return [("1", "rom_cut", cut, "rom_per", per, "右臂壓著切")]

    # DO ... UNTIL i >= .cuts：i = 1 先跑一次，所以 cuts=1 時其實會切 2 刀
    result = []
    i = 1
    while True:
        result.append((str(i), f"chop_1[{i}]", pt(f"chop_1[{i}]"),
                       f"chop_per[{i}]", pt(f"chop_per[{i}]"), ""))
        i += 1
        if i >= cuts:
            break
    result.append((str(i), f"chop_1[{i}]", pt(f"chop_1[{i}]"),
                   f"chop_per[{i}]", pt(f"chop_per[{i}]"), "右臂放開後慢速切"))
    return result


def right_press(press_mm: float, trans: Dict[str, Pose]) -> Tuple[Pose, Pose]:
    if "press_chop_zone" not in trans:
        sys.exit("✗ 右臂教點 press_chop_zone 不存在")
    up = trans["press_chop_zone"]
    down = up[:2] + (up[2] - press_mm,) + up[3:]   # DRAW 0,0,-press_mm（基座座標）
    return up, down


# ============================================================================
# 輸出
# ============================================================================

def fmt_pose(p: Pose) -> str:
    return f"X={p[0]:.3f}  Y={p[1]:.3f}  Z={p[2]:.3f}  O={p[3]:.3f}  A={p[4]:.3f}  T={p[5]:.3f}"


def print_left(cut_list: List[Cut], first_cut_x: float):
    poses = {c[2][3:] for c in cut_list} | {c[4][3:] for c in cut_list}
    print("\n左臂 F60_F（JMOVE #work_chop_zone 之後，每刀：上方 → 下刀 → 上方）")
    if len(poses) == 1:
        o, a, t = poses.pop()
        print(f"  姿態每刀相同: O={o:.3f}  A={a:.3f}  T={t:.3f}")
    print(f"  {'刀':>3}  {'下刀點':<12}{'X':>10}{'Y':>10}{'下刀 Z':>10}{'上方 Z':>10}{'距第一刀':>10}  備註")
    for no, cname, c, _pname, p, note in cut_list:
        print(f"  {no:>3}  {cname:<12}{c[0]:10.3f}{c[1]:10.3f}{c[2]:10.3f}{p[2]:10.3f}"
              f"{c[0] - first_cut_x:10.1f}  {note}")


def print_right(press_mm: float, up: Pose, down: Pose):
    print("\n右臂 F60_R（LMOVE press_chop_zone → 壓下 → 等左臂 → 抬起）")
    print(f"  壓點上方 press_chop_zone : {fmt_pose(up)}")
    print(f"  壓下 {press_mm:g}mm  press_down      : {fmt_pose(down)}")


def compare(actual_args, lookup: Dict[str, Pose], food: str, rom_mid: Optional[float],
            press_mm: float):
    print("\n實際量測比對（實際 − 程式）")
    for name, *xyz in actual_args:
        if name not in lookup:
            print(f"  ✗ {name}: 這次的點位裡沒有這個名稱，可用: {', '.join(sorted(lookup))}")
            continue
        ax, ay, az = (float(v) for v in xyz)
        px, py, pz = lookup[name][:3]
        dx, dy, dz = ax - px, ay - py, az - pz
        print(f"  {name}: ΔX={dx:+.2f}  ΔY={dy:+.2f}  ΔZ={dz:+.2f} mm")

        if name == "rom_cut" and rom_mid is not None:
            print(f"    → rom_mid_mm 建議改成 {rom_mid + dx:.1f}（左臂 INIT_CONST）")
            if abs(dy) > 1 or abs(dz) > 1:
                print("    → Y/Z 的差距來自 chop_1[1]，rom_mid_mm 只能修 X，要修 Y/Z 得重教 chop_1[1]")
        elif name == "press_down":
            print(f"    → press_mm 建議改成 {press_mm - dz:.1f}（右臂 do_chop 的 {food} 分支）")
            if abs(dx) > 1 or abs(dy) > 1:
                print("    → X/Y 的差距要重教 press_chop_zone")
        elif name.startswith(("chop_1[", "chop_per[")):
            print("    → chop_1[] / chop_per[] 是教點陣列：整排平移要重教 chop_1[1]，"
                  "再用左臂 do_chop_test 的 FOR 迴圈重算其餘各點（間距 5mm）")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("food", type=str.upper, choices=sorted(FOODS), help="食材")
    ap.add_argument("--cuts", type=int, help="刀數（預設取 config_phase.FOOD_CUT_PARAMS）")
    ap.add_argument("--rom-mid", type=float, help="預覽用的 rom_mid_mm（預設讀左臂 INIT_CONST）")
    ap.add_argument("--actual", nargs=4, action="append", metavar=("點名", "X", "Y", "Z"),
                    help="手動移過去量到的實際座標，可重複多次")
    args = ap.parse_args()

    left_text, right_text = read_as(LEFT_AS), read_as(RIGHT_AS)
    left_trans, right_trans = read_trans(left_text), read_trans(right_text)

    food = args.food
    cuts = args.cuts or FOOD_CUT_PARAMS[food].num_cuts
    if not 1 <= cuts <= 20:
        print(f"✗ 刀數 {cuts} 超出 AS 端允許的 1～20，手臂會回 ERROR,E4005")
        return 1

    rom_mid = args.rom_mid
    if food == "ROMAINE" and rom_mid is None:
        rom_mid = read_rom_mid(left_text)
        if not rom_mid or rom_mid <= 0:
            print(f"✗ 左臂 INIT_CONST 的 rom_mid_mm = {rom_mid}（未量測），手臂會拒絕切生菜。")
            print("  用 --rom-mid 指定一個值來預覽下刀點，例如 --rom-mid 80")
            return 1

    press_table = read_press_mm(right_text)
    if food not in press_table:
        print(f"✗ 右臂 do_chop 沒有 {food} 的 press_mm，手臂會回 ERROR,E4005")
        return 1
    press_mm = press_table[food]

    print(f"{FOODS[food]} ({food})", end="")
    if food == "ROMAINE":
        print(f"：中間切 1 刀，rom_mid_mm = {rom_mid:g}")
    else:
        print(f"：{cuts} 刀" + ("（⚠️ cuts=1 時 DO_CHOP 迴圈實際會切 2 刀）" if cuts == 1 else ""))
    print(f"右臂 press_mm = {press_mm:g}")
    print(f"教點來源: {LEFT_AS.name} / {RIGHT_AS.name}（.TRANS 區段，單位 mm / deg）")

    cut_list = left_cuts(food, cuts, left_trans, rom_mid)
    up, down = right_press(press_mm, right_trans)
    first_cut_x = left_trans["chop_1[1]"][0]
    print_left(cut_list, first_cut_x)
    print_right(press_mm, up, down)

    xs = [c[2][0] for c in cut_list]
    if len(xs) > 1:
        print(f"\n切割範圍: X {xs[0]:.1f} ～ {xs[-1]:.1f}，跨距 {xs[-1] - xs[0]:.0f}mm"
              f"（每刀間距 {xs[1] - xs[0]:.1f}mm）")

    if args.actual:
        lookup = {"press_chop_zone": up, "press_down": down}
        for _no, cname, c, pname, p, _note in cut_list:
            lookup[cname], lookup[pname] = c, p
        compare(args.actual, lookup, food, rom_mid, press_mm)
    return 0


if __name__ == "__main__":
    sys.exit(main())
