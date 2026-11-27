"""鐵鏟（參數化）。

尺寸量自 V2/圖檔/spatula.step，並修改為：鏟面下緣置中接在握柄彎頭端面上，
鏟面中平面通過彎頭軸線，鏟面與握柄熔接成一體。

執行： cad run V2/cad/spatula.py
匯出： cad model export <id> V2/圖檔/spatula.step
"""
import math

import build123d as bd
from cad import model

# 底座
MOUNT_D = model.param("mount_d", 63.0, min=20, max=150, unit="mm")
MOUNT_H = model.param("mount_h", 12.0, min=2, max=50, unit="mm")
# 握柄
ROD_D = model.param("rod_d", 20.0, min=5, max=40, unit="mm")
ROD_LEN = model.param("rod_len", 143.96, min=20, max=400, unit="mm")  # 直段長
BEND_R = model.param("bend_r", 20.0, min=5, max=100, unit="mm")  # 彎頭中心線半徑
BEND_DEG = model.param("bend_deg", 30.0, min=0, max=90, unit="deg")  # 彎頭角度
TIP_LEN = model.param("tip_len", 20.0, min=0, max=200, unit="mm")  # 彎頭後斜直段
# 鏟面
BLADE_LEN = model.param("blade_len", 150.0, min=20, max=400, unit="mm")  # 沿握柄方向
BLADE_W = model.param("blade_w", 140.0, min=20, max=400, unit="mm")
BLADE_T = model.param("blade_t", 2.0, min=0.5, max=10, unit="mm")
# 補強頸部：握柄端由圓形 Ø ROD_D 漸變為扁平 NECK_W × NECK_T，鏟面下緣埋入頸部
NECK_LEN = model.param("neck_len", 35.0, min=0, max=100, unit="mm")
NECK_W = model.param("neck_w", 60.0, min=10, max=140, unit="mm")
NECK_T = model.param("neck_t", 4.0, min=1, max=20, unit="mm")
BLADE_EMBED = model.param("blade_embed", 25.0, min=0, max=100, unit="mm")  # 鏟面埋入頸部的深度


def handle_path():
    """握柄中心線：直段 → 圓弧彎頭 → 斜直段。回傳 (wire, 端點, 端點方向)。"""
    th = math.radians(BEND_DEG)
    p0 = bd.Vector(0, 0, MOUNT_H)
    p1 = p0 + bd.Vector(0, 0, ROD_LEN)
    direction = bd.Vector(math.sin(th), 0, math.cos(th))
    edges = [bd.Edge.make_line(p0, p1)]
    p2 = p1
    if BEND_DEG > 0:
        center = p1 + bd.Vector(BEND_R, 0, 0)
        p2 = center + bd.Vector(-BEND_R * math.cos(th), 0, BEND_R * math.sin(th))
        edges.append(bd.Edge.make_tangent_arc(p1, bd.Vector(0, 0, 1), p2))
    end = p2 + direction * TIP_LEN
    if TIP_LEN > 0:
        edges.append(bd.Edge.make_line(p2, end))
    return bd.Wire(edges), end, direction


@model
def spatula():
    mount = bd.Cylinder(MOUNT_D / 2, MOUNT_H, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    mount.label = "mount"
    mount.color = "#5f6672"

    path, end, direction = handle_path()
    profile = bd.Face(bd.Wire.make_circle(ROD_D / 2, bd.Plane(origin=(0, 0, MOUNT_H), z_dir=(0, 0, 1))))
    rod = bd.sweep(profile, path=path)

    # 頸部：圓 → 扁平矩形的漸變，分散接縫處的應力
    neck_end = end
    if NECK_LEN > 0:
        neck_end = end + direction * NECK_LEN
        start = bd.Face(bd.Wire.make_circle(ROD_D / 2, bd.Plane(origin=end, x_dir=(0, 1, 0), z_dir=direction)))
        stop = bd.Plane(origin=neck_end, x_dir=(0, 1, 0), z_dir=direction).location * bd.Rectangle(NECK_W, NECK_T)
        rod = rod.fuse(bd.loft([start, stop]))

    # 鏟面：下緣置中埋入頸部 BLADE_EMBED，沿握柄方向延伸，寬度方向為 Y
    blade_plane = bd.Plane(origin=neck_end - direction * BLADE_EMBED, x_dir=(0, 1, 0), z_dir=direction)
    blade = blade_plane.location * bd.Box(
        BLADE_W, BLADE_T, BLADE_LEN, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)
    )

    body = rod.fuse(blade).clean()
    assert len(body.solids()) == 1, "握柄與鏟面沒有接成一體"
    body.label = "spatula"
    body.color = "#aab3bf"

    return bd.Compound(children=[mount, body], label="spatula_assembly")


if __name__ == "__main__":
    spatula()
