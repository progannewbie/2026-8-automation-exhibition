#!/usr/bin/env python3
"""SmartCook V2 吋動面板：像教導器一樣操作兩支 RS007L，並調整煎台位置。

座標模式
  軸 (JOINT)  ：一次轉一軸
  基座 (BASE) ：沿所選手臂自己 base_link 的 X/Y/Z 平移、繞軸旋轉
  工具 (TOOL) ：沿 TCP 自己的軸平移、旋轉
  世界 (WORLD)：沿地面座標（world）平移、旋轉

  平移 / 旋轉都以 TCP 為中心；用幾何 Jacobian + 阻尼最小平方 (DLS) 解逆運動學。

發佈
  /joint_states                 兩支手臂 12 軸
  /smartcook_scene (MarkerArray) 煎台
  TF: world → griddle（煎台頂面中心）、<arm>_link6 → <arm>_tcp

煎台、平鏟尺寸、碰撞設定存在 scene_file（預設 config/scene.yaml），面板上按「儲存設定」寫回。

平鏟
  兩支手臂裝同一組參數化平鏟（法蘭座 + 把手 + 彎折鏟面），TCP 在鏟尖中心、底面上：
  X 往前鏟、Z 朝下（鏟面放平時壓進煎台的方向）。「匯出 STL」存到 V2/圖檔/spatula.stl。

碰撞檢查
  每支手臂 link1～link6 的 3D 模型表面每約 5 mm 取一點，檢查有沒有點進入
  「煎台方塊 + 安全距離」或低於地面。會撞到的吋動直接拒絕；
  若已經在干涉中（例如把煎台移到手臂上），只允許讓干涉變少的動作，方便退出。
  平鏟也一起檢查；平鏟對煎台不留安全距離（可以貼著煎台面，不能壓進去）。

工具
  每支手臂裝平鏟或夾爪（scene.yaml 的 tools；預設兩支都是平鏟）。
  夾爪是參數化平行雙指，TCP 在指尖中心；開合量即時顯示、也算進碰撞檢查。

取料、翻面（都先規劃整條路徑：逆運動學 + 每一步碰撞檢查，全部可行才開始動）
  取料（兩把平鏟）：左鏟放平貼托盤 → 右鏟尖朝下把肉排刮上左鏟 → 左鏟保持水平端到煎台
        → 右鏟擋在肉排後面、左鏟抽出，肉排落到煎台 → 右鏟回出發位置
        → 完整流程：左鏟直接貼著煎台鏟回肉排底下翻面（整段一次規劃、動作連續）。
  取料（有一支是夾爪）：夾起 → 搬到煎台 → 放開。
  翻面：平鏟鏟進肉排底下 → 抬起 → 繞把手方向（轉軸通過肉排中心）轉 180°
        → 肉排滑落、翻面落回煎台 → 轉回 → 退回上方。
  肉排兩半不同顏色：放上煎台後朝下（正在煎）的那面變深褐色。
"""
import math
import os
import sys
import threading
import xml.etree.ElementTree as ET

import numpy as np
import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import Point, TransformStamped
from python_qt_binding.QtCore import Qt, QTimer
from python_qt_binding.QtGui import QFont, QFontDatabase
from python_qt_binding.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QRadioButton, QScrollArea, QSlider, QVBoxLayout, QWidget,
)
from rclpy.node import Node
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation, Slerp
from sensor_msgs.msg import JointState
from tf2_ros import TransformBroadcaster
from visualization_msgs.msg import Marker, MarkerArray

# WSL 預設沒有中文字型：依序找 Linux 已安裝的、再用 Windows 的微軟正黑體
CJK_FONT_FILES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/mnt/c/Windows/Fonts/msjh.ttc",      # 微軟正黑體
    "/mnt/c/Windows/Fonts/msyh.ttc",      # 微軟雅黑
    "/mnt/c/Windows/Fonts/mingliu.ttc",   # 細明體
]

ARMS = ["right_", "left_"]
ARM_NAMES = {"right_": "右臂 (+X)", "left_": "左臂 (-X)"}
ARM_SIDE = {"right_": "右", "left_": "左"}
PICKUP_CARRIER, PICKUP_SCRAPER = "left_", "right_"   # 兩把平鏟取料：左鏟接著端、右鏟刮
MODES = ["JOINT", "BASE", "TOOL", "WORLD"]
MODE_NAMES = {"JOINT": "軸", "BASE": "基座", "TOOL": "工具", "WORLD": "世界"}

MAX_LIN = 0.100              # m/s，100% 速度
MAX_ROT = math.radians(30)   # rad/s
MAX_JNT = math.radians(30)   # rad/s
DT = 0.04                    # 吋動更新週期 (s)
SAMPLE_SPACING = 0.005       # 碰撞取樣點間距 (m)，要小於安全距離
TOOL_GAP = SAMPLE_SPACING    # 兩支手臂的工具（例如兩把平鏟）之間最少要隔多遠 (m)
DLS_LAMBDA = 0.05            # 奇異點附近的最大阻尼
SING_THRESHOLD = 0.04        # Jacobian 最小奇異值低於這個才開始加阻尼

# 翻面：每一格（DT）在 100% 速度時走的量
LIN_STEP = MAX_LIN * DT              # 直線 4 mm
ROT_STEP = MAX_ROT * DT              # 姿態 1.2°
JNT_STEP = MAX_JNT * DT              # 軸 1.2°
FLIP_STEP = math.radians(90) * DT    # 翻鏟時 JT6 3.6°（100% = 90°/s）
PATTY_DEFAULT = {
    "x": 0.0, "y": 0.0,              # 肉排中心（煎台座標，mm）
    "diameter": 110.0, "thickness": 15.0,
    "approach": 180.0,               # 鏟入方向：鏟尖朝向（煎台座標，deg，0 = 煎台 +X）
    "lift": 100.0,                   # 鏟起後抬高（mm）
}
FLIP_GAP = 0.001                     # 鏟面貼煎台滑動時離煎台面的距離 (m)
PLATE_DEFAULT = {
    "x": -350.0, "y": 200.0, "z": 850.0,   # 出餐盤頂面中心（world）：煎台左後角（再往左右鏟搆不到）
    "diameter": 240.0, "thickness": 15.0,
}


# ---------------------------------------------------------------- 數學工具
def rpy_to_mat(r, p, y):
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return np.array([
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ])


def make_T(R, p):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = p
    return T


def axis_angle(axis, ang):
    x, y, z = axis
    c, s, C = math.cos(ang), math.sin(ang), 1 - math.cos(ang)
    return np.array([
        [c + x * x * C, x * y * C - z * s, x * z * C + y * s],
        [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
        [z * x * C - y * s, z * y * C + x * s, c + z * z * C],
    ])


def mat_to_quat(R):
    t = np.trace(R)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        return ((R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s, 0.25 * s)
    i = int(np.argmax([R[0, 0], R[1, 1], R[2, 2]]))
    j, k = (i + 1) % 3, (i + 2) % 3
    s = math.sqrt(1.0 + R[i, i] - R[j, j] - R[k, k]) * 2
    q = [0.0, 0.0, 0.0, 0.0]
    q[i] = 0.25 * s
    q[j] = (R[j, i] + R[i, j]) / s
    q[k] = (R[k, i] + R[i, k]) / s
    q[3] = (R[k, j] - R[j, k]) / s
    return tuple(q)


def resolve_package_uri(uri):
    if uri.startswith("package://"):
        pkg, rel = uri[len("package://"):].split("/", 1)
        return os.path.join(get_package_share_directory(pkg), rel)
    return uri.replace("file://", "")


STL_DTYPE = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])


def sample_stl(path, scale, spacing):
    """讀 STL（binary），在每個三角形表面均勻取點，回傳 (N, 3)，單位 m。"""
    with open(path, "rb") as f:
        data = f.read()
    n = int.from_bytes(data[80:84], "little")
    if 84 + 50 * n != len(data):
        raise ValueError(f"只支援 binary STL：{path}")
    rec = np.frombuffer(data[84:], dtype=STL_DTYPE)
    return sample_triangles(rec["v"].astype(np.float64) * scale, spacing)


def write_stl(path, tri, scale=1.0, name=b"smartcook"):
    """把三角形 (n, 3, 3) 寫成 binary STL。"""
    tri = np.asarray(tri, dtype=np.float64) * scale
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    rec = np.zeros(len(tri), dtype=STL_DTYPE)
    rec["n"], rec["v"] = nrm, tri
    with open(path, "wb") as f:
        f.write(name.ljust(80, b" ")[:80])
        f.write(len(tri).to_bytes(4, "little"))
        f.write(rec.tobytes())


def sample_triangles(tri, spacing):
    """在三角形 (n, 3, 3) 表面均勻取點，回傳 (N, 3)。"""
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    pts = [a, b, c]
    longest = np.max(np.stack([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1),
                               np.linalg.norm(a - c, axis=1)]), axis=0)
    # 依三角形最長邊決定細分數，讓表面上任一點離取樣點都不超過約 spacing
    divs = np.clip(np.ceil(longest / spacing), 1, 200).astype(int)
    for k in np.unique(divs):
        if k <= 1:
            continue
        sel = divs == k
        i, j = np.meshgrid(np.arange(k + 1), np.arange(k + 1), indexing="ij")
        keep = (i + j) <= k
        u, v = (i[keep] / k), (j[keep] / k)
        A, B, C = a[sel][:, None], b[sel][:, None], c[sel][:, None]
        pts.append((A + u[None, :, None] * (B - A) + v[None, :, None] * (C - A)).reshape(-1, 3))
    P = np.concatenate(pts)
    # 體素去重，避免點太多
    key = np.floor(P / (spacing * 0.8)).astype(np.int64)
    _, idx = np.unique(key, axis=0, return_index=True)
    return P[idx]


# ---------------------------------------------------------------- 平鏟（參數化）
#
#  座標都在 link6 法蘭座標（法蘭面 z = 0，Z 朝外）：
#
#        法蘭        把手（沿 +Z）          鏟面
#   z=0 ┃▌▌▌▌▌▌━━━━━━━━━━━━━━━━━━━━━━━━●╲
#        法蘭座                         B  ╲  彎角 α：鏟面放平時把手抬起的角度
#                                           ╲▁▁▁▁▁▁▁▁▁▁▁ ← 鏟尖（TCP）
#
#  鏟面往 f = (sin α, 0, cos α) 延伸；鏟面底面法向 n = (-cos α, 0, sin α)（放平時朝下）
#  鏟面頂面貼在把手末端下緣，鏟面放平時把手不會比鏟面低
#  TCP：鏟尖中心、底面上；X = f（往前鏟）、Y = link6 Y、Z = n（朝下壓進煎台）
SPATULA_DEFAULT = {
    "blade_width": 140.0,      # 鏟面寬
    "blade_length": 150.0,     # 鏟面長（從彎折點到鏟尖）
    "blade_thickness": 2.0,
    "bend_angle": 30.0,        # deg
    "shaft_length": 150.0,     # 把手長（法蘭座到彎折點）
    "shaft_diameter": 20.0,
    "mount_diameter": 63.0,    # 法蘭座
    "mount_thickness": 12.0,
}
SPATULA_PART_NAMES = {"mount": "鏟子法蘭座", "shaft": "鏟子把手", "blade": "鏟面"}


def _cylinder(r, z0, z1, n=32):
    th = np.linspace(0, 2 * math.pi, n + 1)
    ring = np.stack([r * np.cos(th), r * np.sin(th)], axis=1)
    tris = []
    for i in range(n):
        (x0, y0), (x1, y1) = ring[i], ring[i + 1]
        p00, p01, p10, p11 = (x0, y0, z0), (x1, y1, z0), (x0, y0, z1), (x1, y1, z1)
        tris += [(p00, p01, p11), (p00, p11, p10),                  # 側面
                 ((0, 0, z0), p01, p00), ((0, 0, z1), p10, p11)]     # 底、頂
    return np.array(tris, dtype=np.float64)


def _box(origin, ax_u, ax_v, ax_w):
    """以 origin 為角、三個邊向量張成的長方體 12 個三角形。"""
    o, u, v, w = (np.asarray(x, dtype=np.float64) for x in (origin, ax_u, ax_v, ax_w))
    c = [o + i * u + j * v + k * w for i in (0, 1) for j in (0, 1) for k in (0, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return np.array([t for a, b, cc, d in faces for t in ((c[a], c[b], c[cc]), (c[a], c[cc], c[d]))])


def _orient_outward(tri):
    """凸形零件：把法向朝內的三角形翻過來，匯出 STL 給 CAD 時才不會內外顛倒。"""
    center = tri.reshape(-1, 3).mean(axis=0)
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    inward = np.einsum("ij,ij->i", nrm, tri.mean(axis=1) - center) < 0
    tri = tri.copy()
    tri[inward] = tri[inward][:, [0, 2, 1]]
    return tri


def spatula_geometry(p):
    """回傳 ({part: 三角形 (n,3,3)}, T_tcp)，單位 m，座標在 link6 法蘭座標。"""
    mm = 0.001
    a = math.radians(p["bend_angle"])
    f = np.array([math.sin(a), 0.0, math.cos(a)])
    n = np.array([-math.cos(a), 0.0, math.sin(a)])
    y = np.array([0.0, 1.0, 0.0])
    mt, ls = p["mount_thickness"] * mm, p["shaft_length"] * mm
    r = p["shaft_diameter"] * mm / 2
    B = np.array([0.0, 0.0, mt + ls])                    # 彎折點（把手軸線末端）
    W, L, t = p["blade_width"] * mm, p["blade_length"] * mm, p["blade_thickness"] * mm
    # 鏟面頂面要在把手下緣（n 方向 r·cos α），把手才不會凸出鏟面底面
    bottom = B + (r * math.cos(a) + t) * n               # 鏟面底面、彎折處中心
    parts = {
        "mount": _cylinder(p["mount_diameter"] * mm / 2, 0.0, mt),
        "shaft": _cylinder(r, mt, mt + ls),
        # 鏟面：底面在 bottom，往 -n 長厚度 t
        "blade": _box(bottom - W / 2 * y - t * n, L * f, W * y, t * n),
    }
    T_tcp = make_T(np.column_stack([f, y, n]), bottom + L * f)
    return {k: _orient_outward(v) for k, v in parts.items()}, T_tcp


# ---------------------------------------------------------------- 夾爪（參數化，平行雙指）
#
#  座標在 link6 法蘭座標（Z 朝外）：法蘭座 → 本體（長邊沿 Y）→ 兩片夾指沿 Y 對稱開合。
#  TCP：兩指指尖中心；X/Y/Z 和法蘭相同（夾爪朝下時 Z 朝下）。
#  夾肉排：從上方下來，指尖到托盤面上方 2 mm，兩指從左右夾住肉排側面。
GRIPPER_DEFAULT = {
    "body_length": 200.0,      # 本體長（開合方向 Y）
    "body_depth": 50.0,        # 本體寬（X）
    "body_height": 40.0,       # 本體高（Z）
    "finger_length": 80.0,     # 夾指長（Z，從本體底面到指尖）
    "finger_width": 60.0,      # 夾指寬（X）
    "finger_thickness": 6.0,   # 夾指厚（Y）
    "max_open": 160.0,         # 最大張開（兩指內側距離）
    "mount_diameter": 63.0,
    "mount_thickness": 12.0,
}
GRIP_SPEED = 0.100           # 夾指開合速度 (m/s，兩指內側距離)
GRIP_SQUEEZE = 4.0           # 夾肉排時比直徑再夾緊多少 (mm)
TOOL_NAMES = {"spatula": "平鏟", "gripper": "夾爪"}
TOOL_PART_NAMES = {
    "spatula": SPATULA_PART_NAMES,
    "gripper": {"mount": "夾爪法蘭座", "body": "夾爪本體", "finger_l": "夾指", "finger_r": "夾指"},
}
TRAY_DEFAULT = {
    "x": 450.0, "y": 950.0, "z": 850.0, "yaw": 0.0,     # 托盤頂面中心（world）：煎台右前角（兩支手臂動作最順）
    "length": 450.0, "width": 200.0, "thickness": 20.0,
    "count": 3.0, "spacing": 140.0,                     # 沿托盤長邊排幾片、間距
}


def gripper_geometry(p, opening):
    """回傳 ({part: 三角形}, T_tcp)，單位 m；opening = 兩指內側距離 (mm)。"""
    mm = 0.001
    mt = p["mount_thickness"] * mm
    bz0, bz1 = mt, mt + p["body_height"] * mm
    bl, bd = p["body_length"] * mm, p["body_depth"] * mm
    fl, fw, ft = p["finger_length"] * mm, p["finger_width"] * mm, p["finger_thickness"] * mm
    o = min(opening, p["max_open"]) * mm / 2
    parts = {
        "mount": _cylinder(p["mount_diameter"] * mm / 2, 0.0, mt),
        "body": _box((-bd / 2, -bl / 2, bz0), (bd, 0, 0), (0, bl, 0), (0, 0, bz1 - bz0)),
        "finger_l": _box((-fw / 2, o, bz1), (fw, 0, 0), (0, ft, 0), (0, 0, fl)),
        "finger_r": _box((-fw / 2, -o - ft, bz1), (fw, 0, 0), (0, ft, 0), (0, 0, fl)),
    }
    return {k: _orient_outward(v) for k, v in parts.items()}, make_T(np.eye(3), [0, 0, bz1 + fl])


def part_name(arm, link):
    """訊息用的零件名稱：right_link4 → link4、right_tool_spatula_blade → 鏟面。"""
    name = link.replace(arm, "")
    if name.startswith("tool_"):
        tool, _, part = name[len("tool_"):].partition("_")
        return TOOL_PART_NAMES.get(tool, {}).get(part, name)
    return name


def mat_to_oat(R):
    """Kawasaki O/A/T（ZYZ 尤拉角），單位 deg。"""
    a = math.atan2(math.hypot(R[0, 2], R[1, 2]), R[2, 2])
    if abs(math.sin(a)) < 1e-6:
        o = 0.0
        t = math.atan2(R[1, 0], R[0, 0]) if R[2, 2] > 0 else math.atan2(-R[1, 0], -R[0, 0])
    else:
        o = math.atan2(R[1, 2], R[0, 2])
        t = math.atan2(R[2, 1], -R[2, 0])
    return math.degrees(o), math.degrees(a), math.degrees(t)


# ---------------------------------------------------------------- 運動學
class ArmChain:
    """從 URDF 取出 world → <prefix>link6 的串列鏈。"""

    def __init__(self, root, prefix):
        joints = {j.find("child").get("link"): j for j in root.findall("joint")}
        chain, link = [], f"{prefix}link6"
        while link in joints:
            chain.append(joints[link])
            link = joints[link].find("parent").get("link")
        chain.reverse()
        self.prefix = prefix
        self.elems = []   # (T_origin, axis or None, child_link)
        self.names, self.lower, self.upper = [], [], []
        for j in chain:
            o = j.find("origin")
            xyz = [float(v) for v in (o.get("xyz", "0 0 0") if o is not None else "0 0 0").split()]
            rpy = [float(v) for v in (o.get("rpy", "0 0 0") if o is not None else "0 0 0").split()]
            T0 = make_T(rpy_to_mat(*rpy), xyz)
            child = j.find("child").get("link")
            if j.get("type") == "revolute":
                ax = np.array([float(v) for v in j.find("axis").get("xyz").split()])
                lim = j.find("limit")
                self.elems.append((T0, ax / np.linalg.norm(ax), child))
                self.names.append(j.get("name"))
                self.lower.append(float(lim.get("lower")))
                self.upper.append(float(lim.get("upper")))
            else:
                self.elems.append((T0, None, child))
            if child == f"{prefix}base_link":
                self.base_index = len(self.elems)   # 之後的元素屬於手臂
        self.lower, self.upper = np.array(self.lower), np.array(self.upper)

        # 連桿表面取樣點，座標在各自 link frame
        #   points：會動的 link1～link6（自己要檢查的部分）
        #   base_points：固定在立柱上的 base_link（只當作另一支手臂的障礙物）
        self.points, self.base_points = {}, {}
        links = {l.get("name"): l for l in root.findall("link")}
        for _, ax, child in self.elems:
            if ax is None and child != f"{prefix}base_link":
                continue
            vis = links[child].find("visual")
            mesh = vis.find("geometry/mesh") if vis is not None else None
            if mesh is None:
                continue
            scale = float((mesh.get("scale") or "1 1 1").split()[0])
            P = sample_stl(resolve_package_uri(mesh.get("filename")), scale, SAMPLE_SPACING)
            o = vis.find("origin")
            if o is not None:
                Tv = make_T(rpy_to_mat(*[float(v) for v in o.get("rpy", "0 0 0").split()]),
                            [float(v) for v in o.get("xyz", "0 0 0").split()])
                P = P @ Tv[:3, :3].T + Tv[:3, 3]
            (self.points if ax is not None else self.base_points)[child] = P

    def fk(self, q, T_tcp, links=False):
        """回傳 (T_base, T_tcp_world, 各軸位置, 各軸 world 軸向)；links=True 時再加上 {link: T_world}。"""
        T = np.eye(4)
        T_base = None
        pos, axes, link_T = [], [], {}
        qi = 0
        for idx, (T0, ax, child) in enumerate(self.elems):
            T = T @ T0
            if ax is not None:
                pos.append(T[:3, 3].copy())
                axes.append(T[:3, :3] @ ax)
                T = T @ make_T(axis_angle(ax, q[qi]), [0, 0, 0])
                qi += 1
            link_T[child] = T.copy()
            if idx + 1 == self.base_index:
                T_base = T.copy()
        if links:
            return T_base, T @ T_tcp, pos, axes, link_T
        return T_base, T @ T_tcp, pos, axes

    def world_points(self, q, include_base=False):
        """連桿取樣點（world 座標），回傳 {link: (N, 3)}；include_base 時加上 base_link。"""
        link_T = self.fk(q, np.eye(4), links=True)[4]
        src = {**self.points, **self.base_points} if include_base else self.points
        return {l: P @ link_T[l][:3, :3].T + link_T[l][:3, 3] for l, P in src.items()}

    def jacobian(self, q, T_tcp):
        _, Tt, pos, axes = self.fk(q, T_tcp)
        p = Tt[:3, 3]
        J = np.zeros((6, len(q)))
        for i, (pi, zi) in enumerate(zip(pos, axes)):
            J[:3, i] = np.cross(zi, p - pi)
            J[3:, i] = zi
        return J


# ---------------------------------------------------------------- ROS 節點
class JogNode(Node):
    def __init__(self):
        super().__init__("smartcook_jog_panel")
        self.declare_parameter("robot_description", "")
        self.declare_parameter("scene_file", "")
        urdf = self.get_parameter("robot_description").value
        if not urdf:
            raise RuntimeError("robot_description 參數是空的")
        root = ET.fromstring(urdf)
        self.chains = {p: ArmChain(root, p) for p in ARMS}
        self.q = {p: np.zeros(len(self.chains[p].names)) for p in ARMS}

        # 立柱 / 底座：表面取樣點轉到 world，建 KD-tree 查最近距離
        self.base_tree = self.load_static_link(root, "robot_base")
        self._arm_tree = {}        # 另一支手臂的 KD-tree 快取：{arm: (q bytes, tree)}
        self._interf_cache = {}

        self.scene_file = self.get_parameter("scene_file").value
        self.scene = self.load_scene()
        self.flip = None           # 執行中的動作（翻面、取料）：{"arm", "frames", "i"}
        self.grip_open = {p: self.scene["gripper"]["max_open"] for p in ARMS}   # 夾爪目前張開 (mm)
        self._tool_cache = {}
        self.patty = None          # 煎台上 / 工具上的那塊肉排
        self.refill_tray()
        self.reset_patty()

        self.js_pub = self.create_publisher(JointState, "joint_states", 10)
        self.mk_pub = self.create_publisher(MarkerArray, "smartcook_scene", 10)
        self.tf_pub = TransformBroadcaster(self)

    # ---- 場景設定
    def load_scene(self):
        default = {
            "griddle": {"x": 0.0, "y": -600.0, "z": 850.0, "yaw": 0.0,
                        "length": 600.0, "width": 400.0, "thickness": 60.0},
            "spatula": dict(SPATULA_DEFAULT),
            "collision": {"enabled": True, "margin": 10.0},
            "patty": dict(PATTY_DEFAULT),
            "gripper": dict(GRIPPER_DEFAULT),
            "tray": dict(TRAY_DEFAULT),
            "plate": dict(PLATE_DEFAULT),
            "tools": {"right": "spatula", "left": "spatula"},   # 各手臂裝的工具
        }
        if self.scene_file and os.path.exists(self.scene_file):
            with open(self.scene_file, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for k in default:
                default[k].update(data.get(k, {}) or {})
        return default

    def save_scene(self):
        if not self.scene_file:
            return "沒有設定 scene_file，無法儲存"
        header = ("# SmartCook V2 模擬場景設定（jog_panel 的「儲存設定」會覆寫這個檔）\n"
                  "# 長度單位 mm、角度單位 deg；座標都是 world（地面，X/Y 同 CAD）\n")
        with open(self.scene_file, "w", encoding="utf-8") as f:
            f.write(header)
            yaml.safe_dump({k: {kk: (vv if isinstance(vv, (bool, str)) else float(vv)) for kk, vv in v.items()}
                            for k, v in self.scene.items()},
                           f, allow_unicode=True, sort_keys=False)
        return f"已儲存：{os.path.realpath(self.scene_file)}"

    # ---- 工具（平鏟 / 夾爪）
    def tool(self, arm):
        return self.scene["tools"].get(arm.rstrip("_"), "spatula")

    def tool_key(self, arm, opening=None):
        """決定工具外形的參數；夾爪的張開量取到 0.5 mm。"""
        t = self.tool(arm)
        if t == "gripper":
            o = self.grip_open[arm] if opening is None else opening
            return (t, tuple(self.scene["gripper"].values()), round(o * 2) / 2)
        return (t, tuple(self.scene["spatula"].values()))

    def tool_geom(self, arm, opening=None):
        """(三角形 {part}, 取樣點 {part}, T_tcp)，相對 link6；同樣外形就沿用。"""
        key = self.tool_key(arm, opening)
        if key not in self._tool_cache:
            if key[0] == "gripper":
                tris, T_tcp = gripper_geometry(self.scene["gripper"], key[2])
            else:
                tris, T_tcp = spatula_geometry(self.scene["spatula"])
            pts = {k: sample_triangles(v, SAMPLE_SPACING) for k, v in tris.items()}
            if len(self._tool_cache) > 200:
                self._tool_cache.clear()
            self._tool_cache[key] = (tris, pts, T_tcp)
        return self._tool_cache[key]

    def T_tcp(self, arm):
        """TCP（相對 link6）：平鏟 = 鏟尖、夾爪 = 指尖中心。"""
        return self.tool_geom(arm)[2]

    def arm_points(self, arm, q, include_base=False, opening=None):
        """手臂連桿 + 工具的取樣點（world），{名稱: (N, 3)}；工具零件名稱是 <arm>tool_<工具>_<part>。"""
        c = self.chains[arm]
        link_T = c.fk(q, np.eye(4), links=True)[4]
        src = {**c.points, **c.base_points} if include_base else c.points
        out = {l: P @ link_T[l][:3, :3].T + link_T[l][:3, 3] for l, P in src.items()}
        T6 = link_T[f"{arm}link6"]
        tool = self.tool(arm)
        for part, P in self.tool_geom(arm, opening)[1].items():
            out[f"{arm}tool_{tool}_{part}"] = P @ T6[:3, :3].T + T6[:3, 3]
        return out

    def export_tool_stl(self, tool):
        """把目前尺寸的工具匯出成 STL（mm，原點在法蘭面中心、Z 朝外），放在 V2/圖檔/。夾爪用全開。"""
        out_dir = os.path.dirname(os.path.realpath(self.scene_file)) if self.scene_file else os.getcwd()
        v2 = os.path.dirname(os.path.dirname(os.path.dirname(out_dir)))   # .../V2/ros2/<pkg>/config → V2
        if os.path.isdir(os.path.join(v2, "圖檔")):
            out_dir = os.path.join(v2, "圖檔")
        path = os.path.join(out_dir, f"{tool}.stl")
        if tool == "gripper":
            tris = gripper_geometry(self.scene["gripper"], self.scene["gripper"]["max_open"])[0]
        else:
            tris = spatula_geometry(self.scene["spatula"])[0]
        write_stl(path, np.concatenate(list(tris.values())), scale=1000.0,
                  name=f"SmartCook V2 {tool} (mm, flange frame)".encode())
        return f"已匯出：{path}"

    def T_griddle(self):
        g = self.scene["griddle"]
        return make_T(rpy_to_mat(0, 0, math.radians(g["yaw"])), [g["x"] / 1000, g["y"] / 1000, g["z"] / 1000])

    def T_plate(self):
        pl = self.scene["plate"]
        return make_T(np.eye(3), [pl["x"] / 1000, pl["y"] / 1000, pl["z"] / 1000])

    def T_tray(self):
        t = self.scene["tray"]
        return make_T(rpy_to_mat(0, 0, math.radians(t["yaw"])), [t["x"] / 1000, t["y"] / 1000, t["z"] / 1000])

    # ---- 碰撞
    def load_static_link(self, root, link_name):
        """把固定連桿（底座）的模型取樣點轉到 world，回傳 KD-tree。"""
        link = next(l for l in root.findall("link") if l.get("name") == link_name)
        mesh = link.find("visual/geometry/mesh")
        scale = float((mesh.get("scale") or "1 1 1").split()[0])
        P = sample_stl(resolve_package_uri(mesh.get("filename")), scale, SAMPLE_SPACING)
        # 往上找到 world 的固定關節
        joints = {j.find("child").get("link"): j for j in root.findall("joint")}
        T, name = np.eye(4), link_name
        while name in joints:
            o = joints[name].find("origin")
            T = make_T(rpy_to_mat(*[float(v) for v in o.get("rpy", "0 0 0").split()]),
                       [float(v) for v in o.get("xyz", "0 0 0").split()]) @ T
            name = joints[name].find("parent").get("link")
        return cKDTree(P @ T[:3, :3].T + T[:3, 3])

    def other_arm_tree(self, arm, other_q=None):
        """另一支手臂的 KD-tree：(連桿 + base_link, 工具)，姿態沒變就沿用。other_q：規劃時指定它的姿態。"""
        other = ARMS[1] if arm == ARMS[0] else ARMS[0]
        q = self.q[other] if other_q is None else other_q
        key = (other, q.tobytes(), self.tool_key(other))   # 要含手臂名稱：兩支姿態相同時不能拿錯
        cached = self._arm_tree.get(key)
        if cached is None:
            pts = self.arm_points(other, q, include_base=True)
            links = np.concatenate([v for k, v in pts.items() if "tool_" not in k])
            tool = np.concatenate([v for k, v in pts.items() if "tool_" in k])
            cached = (cKDTree(links), cKDTree(tool))
            if len(self._arm_tree) > 32:
                self._arm_tree.clear()
            self._arm_tree[key] = cached
        return cached

    def interference(self, arm, q, with_other_arm=True, opening=None, other_q=None):
        """回傳 (干涉深度總和 m, 最嚴重的連桿, 對象)。0 = 沒有干涉。

        對象：煎台、取料托盤（方塊加安全距離）、地面（z < 0）、立柱 / 底座、另一支手臂（含它的工具）。
        立柱和手臂是取樣點對取樣點的距離，安全距離至少要比取樣間距大才可靠。
        工具（平鏟、夾爪）對煎台、托盤不留安全距離：可以貼著表面，但不能壓進去。
        （平鏟把手在彎折處只比鏟面底面高一個鏟面厚度，留安全距離的話鏟面永遠貼不到煎台。）
        兩支手臂的工具之間只要隔 TOOL_GAP（兩把平鏟要靠很近才能互相刮肉排）。
        opening：規劃時指定夾爪張開量；other_q：規劃時指定另一支手臂的姿態。None = 目前的。
        """
        g, tr, pl = self.scene["griddle"], self.scene["tray"], self.scene["plate"]
        m = self.scene["collision"]["margin"] / 1000
        m_pts = max(m, 2 * SAMPLE_SPACING)
        other = ARMS[1] if arm == ARMS[0] else ARMS[0]
        oq = self.q[other] if other_q is None else other_q
        key = (arm, q.tobytes(), with_other_arm and (oq.tobytes(), self.tool_key(other)),
               tuple(g.values()), tuple(tr.values()), tuple(pl.values()), m, self.tool_key(arm, opening))
        if key in self._interf_cache:
            return self._interf_cache[key]

        boxes = [(self.T_griddle(), g["length"], g["width"], g["thickness"], "煎台"),
                 (self.T_tray(), tr["length"], tr["width"], tr["thickness"], "取料托盤"),
                 (self.T_plate(), pl["diameter"], pl["diameter"], pl["thickness"], "出餐盤")]   # 盤子用外接方塊算
        links_tree, tool_tree = self.other_arm_tree(arm, oq) if with_other_arm else (None, None)
        total, worst, worst_link, what = 0.0, 0.0, "", ""
        for link, P in self.arm_points(arm, q, opening=opening).items():
            mg = 0.0 if "tool_" in link else m      # 工具可以貼著煎台 / 托盤，手臂要留安全距離
            hits = [(-P[:, 2][P[:, 2] < 0], "地面")]
            for Tb, ln, wd, th, name in boxes:
                hx, hy = ln / 2000 + mg, wd / 2000 + mg
                z_lo, z_hi = -th / 1000 - mg, mg
                L = (P - Tb[:3, 3]) @ Tb[:3, :3]          # 轉到方塊座標（原點在頂面中心）
                depth = np.minimum.reduce([hx - L[:, 0], hx + L[:, 0], hy - L[:, 1], hy + L[:, 1],
                                           z_hi - L[:, 2], L[:, 2] - z_lo])
                hits.append((depth[depth > 0], name))
            is_tool = "tool_" in link
            for tree, name, gap in ((self.base_tree, "立柱", m_pts), (links_tree, "另一支手臂", m_pts),
                                    (tool_tree, "另一支手臂的工具", TOOL_GAP if is_tool else m_pts)):
                if tree is None:
                    continue
                d, _ = tree.query(P, distance_upper_bound=gap)
                d = d[np.isfinite(d)]
                hits.append((gap - d, name))
            for arr, name in hits:
                if arr.size:
                    total += float(arr.sum())
                    if arr.max() > worst:
                        worst, worst_link, what = float(arr.max()), link, name
        result = (total, worst_link, what)
        if len(self._interf_cache) > 256:
            self._interf_cache.clear()
        self._interf_cache[key] = result
        return result

    def try_set(self, arm, q, ok_msg=""):
        """碰撞檢查通過才更新手臂姿態，回傳要顯示的訊息。"""
        if not self.scene["collision"]["enabled"]:
            self.q[arm] = q
            return ok_msg
        cur, _, _ = self.interference(arm, self.q[arm])
        new, link, what = self.interference(arm, q)
        if new == 0.0:
            self.q[arm] = q
            return ok_msg
        if new < cur - 1e-9:      # 已在干涉中：允許往脫離的方向動
            self.q[arm] = q
            return f"干涉中（{part_name(arm, link)} 碰到{what}），請往外移"
        return f"停止：{part_name(arm, link)} 會碰到{what}"

    def colliding(self):
        # 手臂互撞是對稱的，只在第一支手臂算一次
        return any(self.interference(p, self.q[p], with_other_arm=(p == ARMS[0]))[0] > 0 for p in ARMS)

    # ---- 吋動
    def jog_joint(self, arm, idx, direction, speed):
        c = self.chains[arm]
        q = self.q[arm].copy()
        q[idx] += direction * MAX_JNT * speed * DT
        if q[idx] < c.lower[idx] or q[idx] > c.upper[idx]:
            return f"JT{idx + 1} 到達極限"
        return self.try_set(arm, q)

    def move_toward(self, arm, target, speed):
        """各軸同步往目標角度走一步（最慢的軸用吋動速度），回傳 (訊息, 是否結束)。"""
        q = self.q[arm]
        diff = target - q
        span = float(np.abs(diff).max())
        step = MAX_JNT * speed * DT
        done = span <= step
        new = target.copy() if done else q + diff * (step / span)
        msg = self.try_set(arm, new)
        if msg.startswith("停止"):
            return msg + "，已停在途中", True
        return (msg or ("已到達輸入角度" if done else "移動中…")), done

    def jog_cart(self, arm, mode, idx, direction, speed):
        c = self.chains[arm]
        T_tcp = self.T_tcp(arm)
        T_base, Tt, _, _ = c.fk(self.q[arm], T_tcp)
        local = np.zeros(6)
        local[idx] = direction * (MAX_LIN if idx < 3 else MAX_ROT) * speed * DT
        R = {"BASE": T_base[:3, :3], "TOOL": Tt[:3, :3], "WORLD": np.eye(3)}[mode]
        twist = np.concatenate([R @ local[:3], R @ local[3:]])
        J = c.jacobian(self.q[arm], T_tcp)
        # 自適應阻尼：離奇異點遠時不加阻尼（精確），靠近時才加，避免軸速爆衝
        s_min = np.linalg.svd(J, compute_uv=False)[-1]
        lam2 = 0.0 if s_min >= SING_THRESHOLD else (1 - (s_min / SING_THRESHOLD) ** 2) * DLS_LAMBDA ** 2
        dq = J.T @ np.linalg.solve(J @ J.T + lam2 * np.eye(6), twist)
        q = self.q[arm] + dq
        bad = [i for i in range(len(q)) if q[i] < c.lower[i] or q[i] > c.upper[i]]
        if bad:
            return "到達軸極限：" + ", ".join(f"JT{i + 1}" for i in bad)
        return self.try_set(arm, q, "接近奇異點（TCP 可能跟不上指令）" if s_min < SING_THRESHOLD else "")

    # ---- 肉排
    # self.patty：煎台上、或在工具上的那一塊（None = 沒有）
    #   mode：rest（放著）/ attached（在平鏟或夾爪上）/ pushed（被平鏟推著走）
    #         / held（被擋住不動，下面的鏟子正在抽走）/ falling（往下掉）
    #   raw：還沒放上煎台（兩面都是生肉色）
    # self.tray_slots：取料托盤上每個位置還有沒有生肉排
    def refill_tray(self):
        self.tray_slots = [True] * max(int(self.scene["tray"]["count"]), 0)

    def tray_slot_T(self, i):
        """托盤第 i 個位置的肉排中心（world）：沿托盤長邊排、置中。"""
        t = self.scene["tray"]
        x = (i - (len(self.tray_slots) - 1) / 2) * t["spacing"] / 1000
        return self.T_tray() @ make_T(np.eye(3), [x, 0, self.scene["patty"]["thickness"] / 2000])

    def reset_patty(self):
        """直接在煎台設定位置放一塊肉排（「從煎台開始」），顏色深的那面朝下。"""
        p = self.scene["patty"]
        self.patty = {"T": self.T_griddle() @ make_T(np.eye(3), [p["x"] / 1000, p["y"] / 1000,
                                                                  p["thickness"] / 2000]),
                      "mode": "rest", "raw": False, "where": "griddle"}

    def update_patty(self, dt):
        """跟著工具移動、或往下掉；dt 是模擬經過的時間 (s)。"""
        pt = self.patty
        if pt is None:
            return
        if pt["mode"] == "attached":
            arm = pt["arm"]
            pt["T"] = self.chains[arm].fk(self.q[arm], self.T_tcp(arm))[1] @ pt["rel"]
            if self.tool(arm) == "spatula" and pt["T"][2, 2] * pt["up0"] < 0.0:   # 鏟面翻過 90°：肉排滑落
                self.release_patty()
        elif pt["mode"] == "pushed":
            arm = pt["arm"]
            tip = self.chains[arm].fk(self.q[arm], self.T_tcp(arm))[1][:3, 3]
            pos = tip + pt["offset"]
            pt["T"] = make_T(pt["T"][:3, :3], [pos[0], pos[1], pt["T"][2, 3]])
        elif pt["mode"] == "falling":
            T0, T1, dur = pt["fall"]
            pt["t"] = min(pt["t"] + dt, dur)
            s = pt["t"] / dur
            pos = T0[:3, 3] + (T1[:3, 3] - T0[:3, 3]) * np.array([s, s, s * s])   # 垂直方向像自由落體
            R = Slerp([0, 1], Rotation.from_matrix([T0[:3, :3], T1[:3, :3]]))(s).as_matrix()
            pt["T"] = make_T(R, pos)
            if s >= 1.0:
                pt["mode"] = "rest"

    def attach_patty(self, arm):
        """肉排放到工具上，之後跟著 TCP 走。
        平鏟：底面貼鏟面頂面。夾爪：夾在兩指中間，指尖比肉排底面高 2 mm。"""
        Tt = self.chains[arm].fk(self.q[arm], self.T_tcp(arm))[1]
        rel = np.linalg.inv(Tt) @ self.patty["T"]
        h = self.scene["patty"]["thickness"]
        if self.tool(arm) == "spatula":
            # TCP 的 Z 朝下（鏟面底面），肉排中心在鏟面頂面上方半個厚度
            rel[2, 3] = -(self.scene["spatula"]["blade_thickness"] + h / 2) / 1000
        else:
            rel[:3, 3] = [0.0, 0.0, -(h / 2 - 2.0) / 1000]
        T = Tt @ rel
        self.patty = {"T": T, "mode": "attached", "arm": arm, "rel": rel,
                      "up0": 1.0 if T[2, 2] >= 0 else -1.0, "raw": self.patty.get("raw", False)}

    def push_from_tray(self, arm, i):
        """平鏟碰到托盤第 i 片，開始推：肉排跟著鏟尖平移（高度、姿態不變）。"""
        self.tray_slots[i] = False
        T = self.tray_slot_T(i)
        tip = self.chains[arm].fk(self.q[arm], self.T_tcp(arm))[1][:3, 3]
        off = T[:3, 3] - tip
        off[2] = 0.0
        self.patty = {"T": T, "mode": "pushed", "arm": arm, "offset": off, "raw": True}

    def pick_from_tray(self, arm, i):
        """夾爪夾起托盤第 i 片。"""
        self.tray_slots[i] = False
        self.patty = {"T": self.tray_slot_T(i), "mode": "rest", "raw": True}
        self.attach_patty(arm)

    def release_patty(self):
        """放開 / 滑落：肉排中心在出餐盤範圍內就落在盤子上，否則落到煎台面上；
        朝上的軸改成最接近目前姿態的上 / 下。"""
        T0 = self.patty["T"]
        Tp = self.T_plate()
        on_plate = np.linalg.norm(T0[:2, 3] - Tp[:2, 3]) < self.scene["plate"]["diameter"] / 2000
        Tg = Tp if on_plate else self.T_griddle()
        L = np.linalg.inv(Tg) @ T0                    # 煎台座標
        z = np.array([0.0, 0.0, 1.0 if L[2, 2] >= 0 else -1.0])
        x = L[:3, 0] - L[2, 0] * np.array([0, 0, 1.0])
        if np.linalg.norm(x) < 1e-6:
            x = L[:3, 1] - L[2, 1] * np.array([0, 0, 1.0])
        x /= np.linalg.norm(x)
        R = np.column_stack([x, np.cross(z, x), z])
        h = self.scene["patty"]["thickness"] / 2000
        T1 = Tg @ make_T(R, [L[0, 3], L[1, 3], h])
        drop = max(T0[2, 3] - T1[2, 3], 0.0)
        self.patty = {"T": T0, "mode": "falling", "t": 0.0, "raw": False, "where": "plate" if on_plate else "griddle",
                      "fall": (T0, T1, max(0.15, math.sqrt(2 * drop / 9.81)))}

    # ---- 逆運動學 / 路徑規劃
    def ik(self, arm, T_goal, q0, iters=200):
        """數值逆運動學（DLS），解不到回傳 None。"""
        c = self.chains[arm]
        T_tcp = self.T_tcp(arm)
        q = np.array(q0, dtype=float)
        for _ in range(iters):
            Tt = c.fk(q, T_tcp)[1]
            e = np.concatenate([T_goal[:3, 3] - Tt[:3, 3],
                                Rotation.from_matrix(T_goal[:3, :3] @ Tt[:3, :3].T).as_rotvec()])
            if np.linalg.norm(e[:3]) < 2e-4 and np.linalg.norm(e[3:]) < 2e-3:
                return q
            for sl, lim in ((slice(0, 3), 0.05), (slice(3, 6), 0.3)):   # 一次最多走 50 mm / 17°
                n = np.linalg.norm(e[sl])
                if n > lim:
                    e[sl] *= lim / n
            J = c.jacobian(q, T_tcp)
            q = np.clip(q + J.T @ np.linalg.solve(J @ J.T + 1e-4 * np.eye(6), e), c.lower, c.upper)
        return None

    def plan_linear(self, arm, q0, T_goal, rot_step=ROT_STEP):
        """TCP 直線 + 姿態球面內插到 T_goal，回傳每一格的軸角度；途中解不到或軸角跳太大回傳 None。"""
        T0 = self.chains[arm].fk(q0, self.T_tcp(arm))[1]
        dist = np.linalg.norm(T_goal[:3, 3] - T0[:3, 3])
        ang = np.linalg.norm(Rotation.from_matrix(T_goal[:3, :3] @ T0[:3, :3].T).as_rotvec())
        n = max(1, math.ceil(max(dist / LIN_STEP, ang / rot_step)))
        slerp = Slerp([0, 1], Rotation.from_matrix([T0[:3, :3], T_goal[:3, :3]]))
        out, q = [], q0
        for i in range(1, n + 1):
            s = i / n
            qn = self.ik(arm, make_T(slerp(s).as_matrix(), T0[:3, 3] + s * (T_goal[:3, 3] - T0[:3, 3])), q, 60)
            if qn is None or np.abs(qn - q).max() > math.radians(10):
                return None
            out.append(qn)
            q = qn
        return out

    @staticmethod
    def plan_joint(q0, q1, step=JNT_STEP):
        n = max(1, math.ceil(float(np.abs(q1 - q0).max()) / step))
        return [q0 + (q1 - q0) * (i / n) for i in range(1, n + 1)]

    def first_hit(self, arm, qs, opening=None, other_q=None):
        """路徑上第一個會碰撞的點的說明，沒有碰撞回傳 None。
        opening：夾爪張開量；other_q：另一支手臂這段期間的姿態（規劃用，None = 目前的）。"""
        if not self.scene["collision"]["enabled"]:
            return None
        for q in qs:
            tot, link, what = self.interference(arm, q, opening=opening, other_q=other_q)
            if tot > 0:
                return f"{part_name(arm, link)} 會碰到{what}"
        return None

    def flip_poses(self, theta, patty_T=None):
        """鏟入方向 theta（deg，煎台座標）時的關鍵 TCP 姿態（world）。patty_T：肉排位置，None = 目前的。"""
        p = self.scene["patty"]
        Tg = self.T_griddle()
        L = np.linalg.inv(Tg) @ (self.patty["T"] if patty_T is None else patty_T)
        c = np.array([L[0, 3], L[1, 3], 0.0])        # 肉排目前位置（煎台座標）
        t = math.radians(theta)
        d = np.array([math.cos(t), math.sin(t), 0.0])
        z = np.array([0.0, 0.0, -1.0])               # 鏟面放平：TCP 的 Z 朝下
        R = np.column_stack([d, np.cross(z, d), z])
        r = p["diameter"] / 2000
        start, end = c - (r + 0.03) * d, c + (r + 0.01) * d   # 鏟尖從肉排前 30 mm 鏟到超過肉排 10 mm
        up = np.array([0.0, 0.0, 1.0])

        def T(xy, h):
            return Tg @ make_T(R, xy + h * up)

        return {"pre": T(start, 0.15), "down": T(start, FLIP_GAP),
                "slide": T(end, FLIP_GAP), "lift": T(end, FLIP_GAP + p["lift"] / 1000)}

    def plan_flip(self, arm, q0, theta0, auto=True, patty_T=None, other_q=None):
        """規劃整個翻面動作。成功回傳 {"frames": [(q, 階段, 事件)], "theta"}，失敗回傳原因字串。
        patty_T / other_q：接在別的動作後面時，用預測的肉排位置、另一支手臂姿態規劃（None = 目前的）。"""
        p, sp = self.scene["patty"], self.scene["spatula"]
        if self.tool(arm) != "spatula":
            return f"{ARM_NAMES[arm]}裝的不是平鏟"
        if patty_T is None and self.patty is None:
            return "煎台上沒有肉排：先「取料放上煎台」或「從煎台開始」"
        if sp["blade_length"] < p["diameter"] + 10:
            return f"鏟面長 {sp['blade_length']:.0f} mm 太短，至少要比肉排直徑多 10 mm"
        if patty_T is None and (self.patty["mode"] != "rest" or self.patty.get("where") == "plate"):
            return "肉排不在煎台上"
        cands = [theta0]
        if auto:
            cands += [theta0 + s * k for k in range(30, 181, 30) for s in (1, -1)]
        seen, reasons = set(), []
        for th in cands:
            th = (th + 180) % 360 - 180
            if round(th) in seen:
                continue
            seen.add(round(th))
            res = self._plan_flip_dir(arm, q0, th, patty_T, other_q)
            if isinstance(res, list):
                return {"frames": res, "theta": th}
            reasons.append(f"{th:.0f}°：{res}")
        return "找不到可行的翻面路徑\n" + "\n".join(reasons[:6]) + ("\n…" if len(reasons) > 6 else "")

    def _plan_flip_dir(self, arm, q0, theta, patty_T=None, other_q=None):
        c = self.chains[arm]
        poses = self.flip_poses(theta, patty_T)
        # 鏟子已經放平貼在煎台、就在鏟入起點旁邊（例如剛把肉排放下來）：直接貼著煎台滑過去，不用先抬高
        T0 = c.fk(q0, self.T_tcp(arm))[1]
        near = (np.linalg.norm(T0[:3, 3] - poses["down"][:3, 3]) < 0.06 and
                np.linalg.norm(Rotation.from_matrix(T0[:3, :3].T @ poses["down"][:3, :3]).as_rotvec()) < 0.1)
        # 先只算運動學（便宜），全部解得到再做碰撞檢查（貴）
        sols = []
        rng = np.random.default_rng(0)
        seeds = [q0, np.zeros(6)]
        for k in range(10):
            if k == 2 and sols:
                break
            s = seeds[k] if k < 2 else rng.uniform(c.lower, c.upper) * 0.8
            q = self.ik(arm, poses["pre"], s)
            if q is not None and all(np.abs(q - o).max() > 1e-2 for o in sols):
                sols.append(q)
        if not sols:
            return "到不了肉排旁邊"
        sols.sort(key=lambda q: float(np.abs(q - q0).sum()))
        why = "鏟入路徑解不到"
        for q_pre in sols[:3]:
            down = self.plan_linear(arm, q0 if near else q_pre, poses["down"])
            slide = down and self.plan_linear(arm, down[-1], poses["slide"])
            lift = slide and self.plan_linear(arm, slide[-1], poses["lift"])
            if not lift:
                continue
            q_up = lift[-1]
            back = self.plan_linear(arm, q_up, poses["pre"])
            if not back:
                continue
            # 翻鏟：像手腕轉鍋鏟一樣繞「把手方向」轉 180°，但轉軸通過肉排中心，
            # 鏟面原地翻過來、手臂留在上方（直接轉 JT6 的話轉軸在鏟面下方，鏟尖會往下掃到煎台）
            T_up = poses["lift"]
            u = c.fk(q_up, np.eye(4))[1][:3, 2]                    # 把手方向 = link6 Z
            pivot = T_up[:3, 3] - (self.scene["patty"]["diameter"] / 2000 + 0.01) * T_up[:3, 0]
            flips = []
            for sign in (1, -1):
                qs, q = [], q_up
                for k in range(1, 7):                              # 每 30° 一個點，弦和圓弧差 < 3 mm
                    Ru = axis_angle(u, sign * k * math.pi / 6)
                    Tk = make_T(Ru @ T_up[:3, :3], pivot + Ru @ (T_up[:3, 3] - pivot))
                    seg = self.plan_linear(arm, q, Tk, FLIP_STEP)
                    if not seg:
                        qs = None
                        break
                    qs += seg
                    q = seg[-1]
                if qs:
                    flips.append(qs)
            if not flips:
                why = "翻鏟時軸極限或奇異點"
                continue
            # 碰撞：局部動作先檢查
            hit = None
            for name, qs in (("下降", down), ("鏟進肉排", slide), ("抬起", lift), ("退回", back)):
                h = self.first_hit(arm, qs, other_q=other_q)
                if h:
                    hit = f"{name}時{h}"
                    break
            if hit:
                why = hit
                continue
            flip = None
            for qs in flips:
                h = self.first_hit(arm, qs, other_q=other_q)
                if h is None:
                    flip = qs
                    break
                why = f"翻鏟時{h}"
            if flip is None:
                continue
            # 移到肉排旁：直接走軸，撞到的話先抬到更高再直線下來
            approach = [] if near else self.plan_joint(q0, q_pre)
            h = self.first_hit(arm, approach, other_q=other_q)
            if h:
                q_high = self.ik(arm, poses["pre"] @ make_T(np.eye(3), [0, 0, -0.25]), q_pre)   # TCP Z 朝下，-Z = 往上
                to_pre = q_high is not None and self.plan_linear(arm, q_high, poses["pre"])
                approach2 = to_pre and self.plan_joint(q0, q_high) + to_pre
                if not approach2 or self.first_hit(arm, approach2, other_q=other_q):
                    why = f"移到肉排旁時{h}"
                    continue
                approach = approach2
            frames = [(q, "移到肉排旁", None) for q in approach]
            frames += [(q, "貼著煎台移到肉排前" if near else "下降", None) for q in down]
            frames += [(q, "鏟進肉排底下", None) for q in slide]
            frames[-1] = (frames[-1][0], "鏟進肉排底下", "attach")
            frames += [(q, "抬起", None) for q in lift]
            frames += [(q, "翻鏟", None) for q in flip]
            frames.append((flip[-1], "翻鏟", "release"))      # 保險：轉完還沒滑落就放開
            frames += [(flip[-1], "等肉排落下", None)] * 12
            frames += [(q, "轉回", None) for q in reversed(flip[:-1])]
            frames.append((q_up, "轉回", None))
            frames += [(q, "退回", None) for q in back]
            return frames
        return why

    @staticmethod
    def joint_cost(q0, q1):
        """移動量：最慢那一軸（決定時間）＋其他軸總和的一部分（避免多餘的甩動）。"""
        d = np.abs(np.asarray(q1) - np.asarray(q0))
        return float(d.max() + 0.3 * d.sum())

    def ik_multi(self, arm, T, q0):
        """從幾個起點解 IK，回傳不重複的解，移動量最小（離 q0 最近、最不甩）的排前面。
        同一次規劃裡同樣的問題會重複問，結果記起來。"""
        memo = getattr(self, "_ik_memo", None)
        if memo is None or len(memo) > 2000:
            memo = self._ik_memo = {}
        key = (arm, np.round(T, 6).tobytes(), np.round(q0, 6).tobytes(), self.tool_key(arm))
        if key in memo:
            return memo[key]
        c = self.chains[arm]
        rng = np.random.default_rng(0)
        seeds = [q0, np.zeros(6)]
        for j in (3, 5):                       # 手腕（JT4 / JT6）轉半圈的起點：常常是比較順的解
            for sgn in (1, -1):
                sd = np.array(q0, dtype=float)
                sd[j] += sgn * math.pi
                seeds.append(np.clip(sd, c.lower, c.upper))
        seeds += [rng.uniform(c.lower, c.upper) * 0.8 for _ in range(4)]
        sols = []
        for seed in seeds:
            q = self.ik(arm, T, seed)
            if q is not None and all(np.abs(q - o).max() > 1e-2 for o in sols):
                sols.append(q)
        sols.sort(key=lambda q: self.joint_cost(q0, q))
        memo[key] = sols
        return sols

    def ik_cost(self, arm, T, q0, rise=0.15):
        """移到 T 上方 rise 的最小移動量（解不到 = 無限大），用來排方向的先後。"""
        sols = self.ik_multi(arm, make_T(T[:3, :3], T[:3, 3] + [0, 0, rise]), q0)
        return self.joint_cost(q0, sols[0]) if sols else math.inf

    def plan_transfer(self, arm, q0, q1, T1, opening=None, other_q=None):
        """q0 走到 q1（TCP 在 T1）：先試直接走軸，撞到的話先抬高 250 mm 再直線下來。
        回傳 (軸角度清單, None) 或 (None, 原因)。"""
        path = self.plan_joint(q0, q1)
        h = self.first_hit(arm, path, opening, other_q)
        if not h:
            return path, None
        T_high = make_T(T1[:3, :3], T1[:3, 3] + [0, 0, 0.25])
        q_high = self.ik(arm, T_high, q1)
        down = q_high is not None and self.plan_linear(arm, q_high, T1)
        if down:
            path2 = self.plan_joint(q0, q_high) + down
            if not self.first_hit(arm, path2, opening, other_q):
                return path2, None
        return None, h

    def grip_frames(self, q, o0, o1, phase, event=None):
        """夾爪在原地開合的幾格；event 放在第一格。"""
        n = max(1, math.ceil(abs(o1 - o0) / (GRIP_SPEED * DT * 1000)))
        out = [(q, phase, None, o0 + (o1 - o0) * i / n) for i in range(1, n + 1)]
        if event:
            out[0] = (q, phase, event, out[0][3])
        return out

    def plan_pick_place(self, arm, q0):
        """夾爪從托盤夾一片生肉排放到煎台的設定位置。成功回傳 {"frames"}，失敗回傳原因。"""
        if self.tool(arm) != "gripper":
            return f"{ARM_NAMES[arm]}沒有裝夾爪"
        if self.patty is not None:
            return "煎台上已經有肉排：先按「重設」清掉"
        slots = [i for i, v in enumerate(self.tray_slots) if v]
        if not slots:
            return "取料托盤空了：按「重設」補滿"
        pp, gp = self.scene["patty"], self.scene["gripper"]
        D, h = pp["diameter"], pp["thickness"]
        if gp["max_open"] < D + 10:
            return f"夾爪最大張開 {gp['max_open']:.0f} mm，要比肉排直徑多 10 mm 以上"
        if gp["finger_length"] < h:
            return "夾指比肉排還短"
        o_open, o_grip = min(gp["max_open"], D + 30), D - GRIP_SQUEEZE
        slot = slots[0]
        Tg = self.T_griddle()
        pick_c = self.tray_slot_T(slot)[:3, 3]
        place_c = (Tg @ np.array([pp["x"] / 1000, pp["y"] / 1000, 0.003 + h / 2000, 1.0]))[:3]  # 離煎台 3 mm 放開
        tip = np.array([0, 0, -(h / 2 - 2.0) / 1000])       # 指尖比肉排底面高 2 mm
        up = np.array([0, 0, 0.12])

        def down_pose(center, yaw):
            # 夾爪朝下：TCP 的 Z 朝下、X 轉 yaw
            R = rpy_to_mat(0, 0, math.radians(yaw)) @ np.diag([1.0, -1.0, -1.0])
            return make_T(R, center + tip)

        def above(T):
            return make_T(T[:3, :3], T[:3, 3] + up)

        why = "夾取位置解不到"
        o_now = self.grip_open[arm]
        # 1. 夾取：張開 → 移到上方 → 下降 → 夾 → 抬起
        pick = None
        for yaw in range(0, 180, 30):        # 夾爪左右對稱，0～150° 就夠
            T_g = down_pose(pick_c, yaw)
            for q_a in self.ik_multi(arm, above(T_g), q0)[:3]:
                down = self.plan_linear(arm, q_a, T_g)
                lift = down and self.plan_linear(arm, down[-1], above(T_g))
                if not lift:
                    continue
                h1 = self.first_hit(arm, down, o_open) or self.first_hit(arm, lift, o_grip)
                if h1:
                    why = f"夾取時{h1}"
                    continue
                go, h2 = self.plan_transfer(arm, q0, q_a, above(T_g), o_open)
                if go is None:
                    why = f"移到托盤時{h2}"
                    continue
                pick = (go, down, lift)
                break
            if pick:
                break
        if not pick:
            return why
        go, down, lift = pick
        frames = self.grip_frames(q0, o_now, o_open, "張開夾爪") if abs(o_now - o_open) > 0.5 else []
        frames += [(q, "移到托盤", None, o_open) for q in go]
        frames += [(q, "下降", None, o_open) for q in down]
        frames += self.grip_frames(down[-1], o_open, o_grip, "夾取")
        frames[-1] = (frames[-1][0], "夾取", ("pick", slot), o_grip)
        frames += [(q, "抬起", None, o_grip) for q in lift]

        # 2. 放上煎台：移到煎台上方 → 下降 → 張開 → 抬起 → 回到出發姿態
        q_up = lift[-1]
        why = "煎台上的放置位置解不到"
        for yaw in range(0, 180, 30):
            T_p = down_pose(place_c, yaw)
            for q_b in self.ik_multi(arm, above(T_p), q_up)[:3]:
                lower = self.plan_linear(arm, q_b, T_p)
                rise = lower and self.plan_linear(arm, lower[-1], above(T_p))
                if not rise:
                    continue
                h1 = self.first_hit(arm, lower, o_grip) or self.first_hit(arm, rise, o_open)
                if h1:
                    why = f"放上煎台時{h1}"
                    continue
                move, h2 = self.plan_transfer(arm, q_up, q_b, above(T_p), o_grip)
                if move is None:
                    why = f"搬到煎台時{h2}"
                    continue
                frames += [(q, "搬到煎台", None, o_grip) for q in move]
                frames += [(q, "放下", None, o_grip) for q in lower]
                frames += self.grip_frames(lower[-1], o_grip, o_open, "放開", "release")
                frames += [(q, "抬起", None, o_open) for q in rise]
                home, _ = self.plan_transfer(arm, rise[-1], q0, self.chains[arm].fk(q0, self.T_tcp(arm))[1], o_open)
                frames += [(q, "回到出發位置", None, o_open) for q in (home or [])]
                return {"frames": frames, "title": "取料"}
        return why

    # ---- 兩把平鏟：取料
    def spatula_pose(self, T_surf, tip_xy, u, height, tilt=0.0):
        """平鏟 TCP 姿態（world）。
        T_surf：表面座標（煎台 / 托盤頂面中心）；tip_xy：鏟尖位置；u：鏟尖朝向（表面座標 xy 單位向量）；
        height：鏟尖最低點離表面多高 (m)；tilt：鏟尖往下傾的角度 (rad)，0 = 鏟面放平。"""
        ux = np.array([u[0], u[1], 0.0])
        z = np.array([0.0, 0.0, -1.0])
        R = np.column_stack([ux, np.cross(z, ux), z])
        if tilt:
            R2 = R @ axis_angle((0, 1, 0), tilt)
            R = R2 if R2[2, 0] < 0 else R @ axis_angle((0, 1, 0), -tilt)   # 鏟尖朝下
        t = self.scene["spatula"]["blade_thickness"] / 1000
        low = min(0.0, -t * R[2, 2])          # 鏟尖頂面那條邊（TCP − t·Z）可能比 TCP 低
        return T_surf @ make_T(R, [tip_xy[0], tip_xy[1], height - low])

    def approach(self, arm, q0, T, other_q, rise=0.15, prefer=None):
        """從 q0 移到 T 上方 rise，再直線下到 T。回傳 (軸角度清單, None) 或 (None, 原因)。
        prefer：上方那一點想要的手臂姿勢（軸角度），有的話先試。"""
        why = "到不了"
        T_pre = make_T(T[:3, :3], T[:3, 3] + [0, 0, rise])
        sols = self.ik_multi(arm, T_pre, q0)[:3]
        if prefer is not None:
            q = self.ik(arm, T_pre, prefer)
            if q is not None:
                sols = [q] + sols
        for q_pre in sols:
            down = self.plan_linear(arm, q_pre, T)
            if not down:
                why = "下降路徑解不到"
                continue
            h = self.first_hit(arm, down, other_q=other_q)
            if h:
                why = f"下降時{h}"
                continue
            go, h = self.plan_transfer(arm, q0, q_pre, T_pre, other_q=other_q)
            if go is None:
                why = f"移過去時{h}"
                continue
            return go + down, None
        return None, why

    def max_tilt(self, arm, qs):
        """路徑上鏟面最大傾斜角 (rad)：TCP 的 Z（鏟面底面法向）和正下方的夾角。"""
        c, T_tcp = self.chains[arm], self.T_tcp(arm)
        return max((math.acos(np.clip(-c.fk(q, T_tcp)[1][2, 2], -1, 1)) for q in qs), default=0.0)

    def carry(self, arm, q0, T, other_q, rise=0.15, max_tilt=math.radians(30)):
        """端著肉排移到 T 上方 rise 再直線下到 T，全程鏟面傾斜不超過 max_tilt（不然肉排會滑掉）。
        先試直線（鏟面一直放平），撞到或解不到再試走軸。回傳 (軸角度清單, None) 或 (None, 原因)。"""
        T_pre = make_T(T[:3, :3], T[:3, 3] + [0, 0, rise])
        why = "端過去的路徑解不到"
        options = []
        straight = self.plan_linear(arm, q0, T_pre)
        if straight:
            options.append(straight)
        for q_pre in self.ik_multi(arm, T_pre, q0)[:3]:
            options.append(self.plan_joint(q0, q_pre))
            T_high = make_T(T[:3, :3], T[:3, 3] + [0, 0, rise + 0.25])      # 先抬高再過去
            q_high = self.ik(arm, T_high, q0)
            up_path = q_high is not None and self.plan_linear(arm, q0, T_high)
            down_path = up_path and self.plan_linear(arm, up_path[-1], T_pre)
            if down_path:
                options.append(up_path + down_path)
        for path in options:
            if self.max_tilt(arm, path) > max_tilt:
                why = f"端過去時鏟面會傾斜超過 {math.degrees(max_tilt):.0f}°（肉排會滑掉）"
                continue
            h = self.first_hit(arm, path, other_q=other_q)
            if h:
                why = f"端過去時{h}"
                continue
            down = self.plan_linear(arm, path[-1], T)
            if not down:
                why = "放下路徑解不到"
                continue
            h = self.first_hit(arm, down, other_q=other_q)
            if h:
                why = f"放下時{h}"
                continue
            return path + down, None
        return None, why

    def lin(self, arm, q0, T, other_q, what):
        """直線移動 + 碰撞檢查，回傳 (軸角度清單, None) 或 (None, 原因)。"""
        path = self.plan_linear(arm, q0, T)
        if not path:
            return None, f"{what}路徑解不到"
        h = self.first_hit(arm, path, other_q=other_q)
        return (None, f"{what}時{h}") if h else (path, None)

    def plan_two_spatula(self, rcv, scr, q0r, q0s, then_flip=False, then_serve=False):
        """兩把平鏟取料：scr（刮的那支）把托盤上的肉排刮到 rcv（接的那支）的鏟面上，
        rcv 端到煎台，scr 從後面擋住肉排、rcv 往後抽出來，肉排落在煎台設定位置。
        then_flip：放下後接著用 rcv 翻面（不回出發位置、不另外規劃）。
        方向（托盤上刮的方向、煎台上放的方向）先用 IK 粗估移動量排序，動最少的先試，動作比較順。
        成功回傳 {"frames"}（每格是 {手臂: 軸角度}），失敗回傳原因。"""
        pp, sp = self.scene["patty"], self.scene["spatula"]
        if self.tool(rcv) != "spatula" or self.tool(scr) != "spatula":
            return "兩支手臂都要裝平鏟"
        if self.patty is not None:
            where = "出餐盤上" if self.patty.get("where") == "plate" else "煎台上"
            return f"{where}已經有肉排：先按「重設」清掉"
        slots = [i for i, v in enumerate(self.tray_slots) if v]
        if not slots:
            return "取料托盤空了：按「重設」補滿"
        if sp["blade_length"] < pp["diameter"] + 10:
            return f"鏟面長 {sp['blade_length']:.0f} mm 太短，至少要比肉排直徑多 10 mm"
        slot = slots[0]
        self._ik_memo = {}
        r, t = pp["diameter"] / 2000, sp["blade_thickness"] / 1000
        lift = pp["lift"] / 1000
        tilt = math.radians(45)               # 刮的那支鏟尖朝下 45°，像一面牆推肉排
        T_tray, T_g = self.T_tray(), self.T_griddle()
        P = (np.linalg.inv(T_tray) @ self.tray_slot_T(slot))[:2, 3]
        G = np.array([pp["x"], pp["y"]]) / 1000

        def up(T, dz):
            return make_T(T[:3, :3], T[:3, 3] + [0, 0, dz])

        # ---- 1. 刮上鏟面（在托盤上）
        #   rcv 鏟面放平，鏟尖朝向肉排（d），停在肉排前 10 mm
        #   scr 從肉排另一邊（+d 那側）往 -d 推，推到鏟尖離 rcv 鏟尖 8 mm
        def pick_poses(th):
            d = np.array([math.cos(math.radians(th)), math.sin(math.radians(th))])
            return (d, self.spatula_pose(T_tray, P - (r + 0.010) * d, d, FLIP_GAP),
                    self.spatula_pose(T_tray, P + (r + 0.030) * d, -d, 0.003, tilt))

        # 擋肉排的那支有兩種拿法（鏟尖都在肉排正後方、比接的鏟面高 6 mm）：
        #   +1：鏟尖朝肉排、鏟面往後翹 45°（像一面牆）
        #   -1：鏟尖朝外、鏟面斜靠在肉排上方 60°（和刮的時候同一個朝向，手臂不用大翻轉）
        def place_poses(ph, way):
            d = np.array([math.cos(math.radians(ph)), math.sin(math.radians(ph))])
            T_sh = self.spatula_pose(T_g, G - (r + 0.003) * d, way * d, FLIP_GAP + t + 0.006,
                                     tilt if way > 0 else math.radians(60))
            return self.spatula_pose(T_g, G + (r - 0.008) * d, d, FLIP_GAP), T_sh

        # 刮的那支：托盤上刮的姿勢要和等一下在煎台上擋的姿勢同一邊（手肘、手腕），
        # 不然中間要整個翻過去（JT3、JT5 轉 200° 左右）。先把兩邊所有姿勢解出來配對，挑最接近的。
        cs = self.chains[scr]
        rng = np.random.default_rng(1)
        seeds = [q0s, np.zeros(6)] + [rng.uniform(cs.lower, cs.upper) * 0.9 for _ in range(8)]

        def all_sols(T):
            out = []
            for sd in seeds:
                q = self.ik(scr, T, sd)
                if q is not None and all(np.abs(q - o).max() > 0.05 for o in out):
                    out.append(q)
            return out

        holds = [q for ph in range(0, 360, 30) for way in (1, -1)
                 for q in all_sols(up(place_poses(ph, way)[1], 0.12))]
        prefer, pair_cost = {}, {}
        for th in range(0, 360, 30):
            best = (math.inf, None)
            for qa in all_sols(up(pick_poses(th)[2], 0.15)):
                cost = min((self.joint_cost(qa, qb) for qb in holds), default=math.inf) \
                    + 0.3 * self.joint_cost(q0s, qa)
                best = min(best, (cost, qa), key=lambda x: x[0])
            pair_cost[th], prefer[th] = best

        # 每個方向先粗估要動多少，動最少（最順）的先試。從出發姿態第一次移過去的量只算一部分
        # （只發生一次），主要看刮完到煎台擋肉排之間順不順。
        order = sorted(range(0, 360, 30),
                       key=lambda th: 0.3 * self.ik_cost(rcv, pick_poses(th)[1], q0r) + pair_cost[th])
        reasons, pick = [], None
        for th in order:
            d = np.array([math.cos(math.radians(th)), math.sin(math.radians(th))])
            T_r = self.spatula_pose(T_tray, P - (r + 0.010) * d, d, FLIP_GAP)
            T_s0 = self.spatula_pose(T_tray, P + (r + 0.030) * d, -d, 0.003, tilt)
            T_s1 = self.spatula_pose(T_tray, P - (r + 0.002) * d, -d, 0.003, tilt)
            r_in, why = self.approach(rcv, q0r, T_r, q0s)
            if why:
                reasons.append(f"{th}°：{ARM_NAMES[rcv]}{why}")
                continue
            s_in, why = self.approach(scr, q0s, T_s0, r_in[-1], prefer=prefer[th])
            push = s_in and self.lin(scr, s_in[-1], T_s1, r_in[-1], "推肉排")
            s_out = push and push[0] and self.lin(scr, push[0][-1], up(T_s1, 0.12), r_in[-1], "抬起")
            if why or not push[0] or not s_out[0]:
                reasons.append(f"{th}°：{ARM_NAMES[scr]}{why or push[1] or s_out[1]}")
                continue
            r_up, why = self.lin(rcv, r_in[-1], up(T_r, lift), s_out[0][-1], "抬起")
            if why:
                reasons.append(f"{th}°：{ARM_NAMES[rcv]}{why}")
                continue
            pick = (r_in, s_in, push[0], s_out[0], r_up, 0.030 / (2 * r + 0.032), T_s0)
            break
        if not pick:
            return "托盤上刮不到肉排（每個方向失敗的原因）\n" + "\n".join(reasons)
        r_in, s_in, push, s_out, r_up, contact, T_s0 = pick
        qr, qs = r_up[-1], s_out[-1]

        # ---- 2. 放上煎台（肉排中心在鏟尖後 r - 8 mm）
        place = self.plan_drop(rcv, scr, qr, qs, T_g, G, r - 0.008, "煎台")
        if isinstance(place, str):
            return place
        r_go, s_go, pull, r_out, s_back, drop, ph = (place[k] for k in
                                                     ("go", "hold", "pull", "r_up", "s_up", "drop", "dir"))

        # ---- 組成每一格兩支手臂的姿態
        cur = {rcv: q0r, scr: q0s}
        frames = []

        def add(arm, qs, phase, events=None):
            for i, q in enumerate(qs):
                cur[arm] = q
                frames.append((dict(cur), phase, (events or {}).get(i)))

        rn, sn = ARM_SIDE[rcv], ARM_SIDE[scr]
        add(rcv, r_in, f"{rn}鏟移到托盤")
        add(scr, s_in, f"{sn}鏟移到肉排後面")
        add(scr, push, f"{sn}鏟把肉排刮上{rn}鏟", {min(int(len(push) * contact), len(push) - 1): ("push", scr, slot),
                                                 len(push) - 1: ("attach", rcv)})
        add(scr, s_out, f"{sn}鏟抬起")
        add(rcv, r_up, f"{rn}鏟端起肉排")
        add(rcv, r_go, "搬到煎台")
        add(scr, s_go, f"{sn}鏟擋在肉排後面")
        add(rcv, pull, f"{rn}鏟抽出、肉排落到煎台",
            {0: ("hold",), min(int(len(pull) * drop), len(pull) - 1): "release"})
        add(scr, s_back, f"{sn}鏟抬起")
        # 刮的那支讓出煎台：回到托盤上方（準備下一片），不行再回出發姿態
        T_ready = make_T(T_s0[:3, :3], T_s0[:3, 3] + [0, 0, 0.15])
        s_home, ready_name = None, f"{sn}鏟回到托盤上方"
        for q_ready in self.ik_multi(scr, T_ready, s_back[-1])[:3]:
            s_home, _ = self.plan_transfer(scr, s_back[-1], q_ready, T_ready, other_q=pull[-1])
            if s_home:
                break
        if not s_home:
            s_home, _ = self.plan_transfer(scr, s_back[-1], q0s, self.chains[scr].fk(q0s, self.T_tcp(scr))[1],
                                           other_q=pull[-1])
            ready_name = f"{sn}鏟回到出發位置"
        add(scr, s_home or [], ready_name)
        if then_flip:
            # 接著翻面：rcv 現在鏟面放平、就在肉排後面，先試同一個方向直接貼著煎台鏟回去
            G_T = T_g @ make_T(np.eye(3), [G[0], G[1], pp["thickness"] / 2000])
            flip = self.plan_flip(rcv, pull[-1], float(ph), True, G_T, cur[scr])
            if isinstance(flip, str):
                return "放上煎台可以，但接著翻面不行：\n" + flip
            for q, phase, ev in flip["frames"]:
                cur[rcv] = q
                frames.append((dict(cur), phase, ev))
            if not then_serve:
                return {"frames": frames, "title": "取料 → 翻面", "theta": flip["theta"]}
            # 接著上菜：翻完的肉排（朝下的那面已經翻上來）還在差不多同一個位置
            flipped = T_g @ make_T(np.diag([1.0, -1.0, -1.0]), [G[0], G[1], pp["thickness"] / 2000])
            serve = self.plan_serve(rcv, scr, cur[rcv], cur[scr], flipped)
            if isinstance(serve, str):
                return "取料、翻面可以，但接著上菜不行：\n" + serve
            frames += serve["frames"]
            return {"frames": frames, "title": "取料 → 翻面 → 上菜", "theta": flip["theta"]}
        add(rcv, r_out, f"{rn}鏟抬起")
        r_home, _ = self.plan_transfer(rcv, r_out[-1], q0r, self.chains[rcv].fk(q0r, self.T_tcp(rcv))[1],
                                       other_q=cur[scr])
        add(rcv, r_home or [], f"{rn}鏟回到出發位置")
        return {"frames": frames, "title": "取料"}

    def plan_drop(self, rcv, scr, qr, qs, T_surf, C, off, where):
        """兩把平鏟把肉排放到某個表面（煎台、出餐盤）：
        rcv 端著肉排（肉排中心在鏟尖後 off）保持水平移過去、鏟面放平貼表面，肉排中心對準 C（表面座標 xy）；
        scr 鏟尖擋在肉排正後方（比 rcv 鏟面高 6 mm），rcv 往後抽出、肉排落下；scr 先抬、rcv 再抬。
        放的方向和 scr 的拿法挑兩支手臂動得最少的。成功回傳 dict，失敗回傳原因。"""
        r = self.scene["patty"]["diameter"] / 2000
        t = self.scene["spatula"]["blade_thickness"] / 1000
        C = np.asarray(C, dtype=float)

        def up(T, dz):
            return make_T(T[:3, :3], T[:3, 3] + [0, 0, dz])

        # 擋肉排的那支有兩種拿法：+1 鏟尖朝肉排、鏟面往後翹 45°；-1 鏟尖朝外、鏟面斜靠在肉排上方 60°
        def poses(ph, way):
            d = np.array([math.cos(math.radians(ph)), math.sin(math.radians(ph))])
            T_sh = self.spatula_pose(T_surf, C - (r + 0.003) * d, way * d, FLIP_GAP + t + 0.006,
                                     math.radians(45 if way > 0 else 60))
            return self.spatula_pose(T_surf, C + off * d, d, FLIP_GAP), T_sh

        def cost(pw):
            return self.ik_cost(rcv, poses(*pw)[0], qr) + self.ik_cost(scr, poses(*pw)[1], qs)

        order = sorted(((ph, way) for ph in range(0, 360, 30) for way in (1, -1)), key=cost)
        reasons = []
        for ph, way in order:
            if math.isinf(cost((ph, way))):
                reasons.append(f"{ph}°：到不了")
                continue
            d = np.array([math.cos(math.radians(ph)), math.sin(math.radians(ph))])
            T_rp, T_sh = poses(ph, way)
            T_rw = self.spatula_pose(T_surf, C - (r + 0.023) * d, d, FLIP_GAP)
            r_go, why = self.carry(rcv, qr, T_rp, qs)
            if why:
                reasons.append(f"{ph}°：{ARM_NAMES[rcv]}{why}")
                continue
            s_go, why = self.approach(scr, qs, T_sh, r_go[-1])
            if why:
                reasons.append(f"{ph}°：{ARM_NAMES[scr]}{why}")
                continue
            pull, why = self.lin(rcv, r_go[-1], T_rw, s_go[-1], "抽出")
            if why:
                reasons.append(f"{ph}°：{ARM_NAMES[rcv]}{why}")
                continue
            # 先抬擋的那支（它在接的那支鏟面上方），再抬接的那支
            s_up, why = self.lin(scr, s_go[-1], up(T_sh, 0.12), pull[-1], "抬起")
            if why:
                reasons.append(f"{ph}°：{ARM_NAMES[scr]}{why}")
                continue
            r_up, why = self.lin(rcv, pull[-1], up(T_rw, 0.12), s_up[-1], "抬起")
            if why:
                reasons.append(f"{ph}°：{ARM_NAMES[rcv]}{why}")
                continue
            return {"go": r_go, "hold": s_go, "pull": pull, "s_up": s_up, "r_up": r_up,
                    "drop": off / (off + r + 0.023), "dir": ph}
        return f"{where}上放不下去（每個方向失敗的原因）\n" + "\n".join(reasons)

    def plan_scoop(self, arm, q0, patty_T, other_q):
        """平鏟從煎台把肉排鏟起來（和翻面前半段一樣：貼煎台、往前鏟、抬起），方向挑動得最少的。
        回傳 (移過去 + 下降, 鏟進去, 抬起, 方向) 或原因字串。"""
        def pose(th):
            return self.flip_poses(th, patty_T)["down"]

        order = sorted(range(0, 360, 30), key=lambda th: self.ik_cost(arm, pose(th), q0))
        reasons = []
        for th in order:
            poses = self.flip_poses(th, patty_T)
            go, why = self.approach(arm, q0, poses["down"], other_q)
            slide = go and self.lin(arm, go[-1], poses["slide"], other_q, "鏟進肉排")
            lift = slide and slide[0] and self.lin(arm, slide[0][-1], poses["lift"], other_q, "抬起")
            if why or not slide[0] or not lift[0]:
                reasons.append(f"{th}°：{why or slide[1] or lift[1]}")
                continue
            return go, slide[0], lift[0], th
        return "煎台上鏟不起肉排（每個方向失敗的原因）\n" + "\n".join(reasons)

    def plan_serve(self, rcv, scr, q0r, q0s, patty_T=None):
        """上菜：rcv 從煎台鏟起肉排 → 端到出餐盤 → scr 擋住、rcv 抽出，肉排落在盤子正中間
        → 兩支回到出發姿態。patty_T：接在翻面後面時用預測的肉排位置。
        成功回傳 {"frames"}（每格 {手臂: 軸角度}），失敗回傳原因。"""
        if self.tool(rcv) != "spatula" or self.tool(scr) != "spatula":
            return "兩支手臂都要裝平鏟"
        if patty_T is None:
            if self.patty is None or self.patty["mode"] != "rest" or self.patty.get("where") == "plate":
                return "煎台上沒有肉排可以上菜"
            patty_T = self.patty["T"]
        r = self.scene["patty"]["diameter"] / 2000
        scoop = self.plan_scoop(rcv, q0r, patty_T, q0s)
        if isinstance(scoop, str):
            return scoop
        go, slide, lift, _ = scoop
        # 鏟完肉排中心在鏟尖後 r + 10 mm（翻面的鏟法：鏟尖超過肉排 10 mm）
        drop = self.plan_drop(rcv, scr, lift[-1], q0s, self.T_plate(), (0.0, 0.0), r + 0.010, "出餐盤")
        if isinstance(drop, str):
            return drop

        cur = {rcv: q0r, scr: q0s}
        frames = []

        def add(arm, qs, phase, events=None):
            for i, q in enumerate(qs):
                cur[arm] = q
                frames.append((dict(cur), phase, (events or {}).get(i)))

        rn, sn = ARM_SIDE[rcv], ARM_SIDE[scr]
        add(rcv, go, f"{rn}鏟移到肉排旁")
        add(rcv, slide, f"{rn}鏟鏟起肉排", {len(slide) - 1: ("attach", rcv)})
        add(rcv, lift, f"{rn}鏟端起肉排")
        add(rcv, drop["go"], "端到出餐盤")
        add(scr, drop["hold"], f"{sn}鏟擋在肉排後面")
        add(rcv, drop["pull"], f"{rn}鏟抽出、肉排落到盤子上",
            {0: ("hold",), min(int(len(drop["pull"]) * drop["drop"]), len(drop["pull"]) - 1): "release"})
        add(scr, drop["s_up"], f"{sn}鏟抬起")
        add(rcv, drop["r_up"], f"{rn}鏟抬起")
        for arm, name in ((scr, sn), (rcv, rn)):     # 兩支回到出發姿態（回不去就停在上方）
            home, _ = self.plan_transfer(arm, cur[arm], (q0s if arm == scr else q0r),
                                         self.chains[arm].fk(q0s if arm == scr else q0r, self.T_tcp(arm))[1],
                                         other_q=cur[rcv if arm == scr else scr])
            add(arm, home or [], f"{name}鏟回到出發位置")
        return {"frames": frames, "title": "上菜"}

    def start_motion(self, arm, plan, title="翻面"):
        self.flip = {"arm": arm, "frames": plan["frames"], "i": 0.0, "n": 0, "title": plan.get("title", title)}

    def flip_tick(self, speed):
        """播放動作（翻面 / 取料）一格，回傳 (訊息, 是否結束)。"""
        f = self.flip
        f["i"] += speed
        while f["n"] < min(int(f["i"]), len(f["frames"])):
            q, phase, ev, *rest = f["frames"][f["n"]]
            arm = f["arm"]
            if isinstance(q, dict):        # 兩支手臂的格子
                self.q.update(q)
            else:
                self.q[arm] = q
            if rest and rest[0] is not None:
                self.grip_open[arm] = rest[0]
            if ev == "attach":
                self.attach_patty(arm)
            elif isinstance(ev, tuple) and ev[0] == "pick":
                self.pick_from_tray(arm, ev[1])
            elif isinstance(ev, tuple) and ev[0] == "push":
                self.push_from_tray(ev[1], ev[2])
            elif isinstance(ev, tuple) and ev[0] == "attach":
                self.attach_patty(ev[1])
            elif isinstance(ev, tuple) and ev[0] == "hold" and self.patty is not None:
                self.patty["mode"] = "held"
            elif ev == "release" and self.patty is not None and self.patty["mode"] in ("attached", "held"):
                self.release_patty()
            self.update_patty(DT)
            f["n"] += 1
        if f["n"] >= len(f["frames"]):
            self.update_patty(DT)       # 動作播完，肉排如果還在掉就讓它落地
            if self.patty is None or self.patty["mode"] != "falling":
                self.flip = None
                return f"{f['title']}完成", True
        phase = f["frames"][max(f["n"] - 1, 0)][1]
        return f"{f['title']}中：{phase}", False

    # ---- 發佈
    def publish(self, hit=False):
        now = self.get_clock().now().to_msg()
        js = JointState()
        js.header.stamp = now
        js.name = [n for p in ARMS for n in self.chains[p].names]
        js.position = [float(v) for p in ARMS for v in self.q[p]]
        self.js_pub.publish(js)

        tfs = []
        Tg = self.T_griddle()
        tfs.append(self.tf_msg(now, "world", "griddle", Tg))
        for p in ARMS:
            tfs.append(self.tf_msg(now, f"{p}link6", f"{p}tcp", self.T_tcp(p)))
        self.tf_pub.sendTransform(tfs)

        g = self.scene["griddle"]
        body = Marker()
        body.header.frame_id = "griddle"   # stamp 留 0：用最新 TF，避免閃爍
        body.ns, body.id, body.type, body.action = "griddle", 0, Marker.CUBE, Marker.ADD
        body.pose.position.z = -g["thickness"] / 2000
        body.pose.orientation.w = 1.0
        body.scale.x, body.scale.y, body.scale.z = g["length"] / 1000, g["width"] / 1000, g["thickness"] / 1000
        body.color.r, body.color.g, body.color.b, body.color.a = 0.15, 0.15, 0.17, 1.0
        top = Marker()
        top.header = body.header
        top.ns, top.id, top.type, top.action = "griddle", 1, Marker.CUBE, Marker.ADD
        top.pose.position.z = 0.0005
        top.pose.orientation.w = 1.0
        top.scale.x, top.scale.y, top.scale.z = g["length"] / 1000 - 0.02, g["width"] / 1000 - 0.02, 0.001
        if hit:   # 干涉中：煎台面變紅
            top.color.r, top.color.g, top.color.b, top.color.a = 1.0, 0.0, 0.0, 1.0
        else:
            top.color.r, top.color.g, top.color.b, top.color.a = 0.85, 0.35, 0.1, 0.9
        label = Marker()
        label.header = body.header
        label.ns, label.id, label.type, label.action = "griddle", 2, Marker.TEXT_VIEW_FACING, Marker.ADD
        label.pose.position.z = 0.08
        label.pose.orientation.w = 1.0
        label.scale.z = 0.05
        label.color.r = label.color.g = label.color.b = label.color.a = 1.0
        label.text = "GRIDDLE"   # RViz 文字標記不一定有中文字型
        markers = [body, top, label]

        # 托盤
        t = self.scene["tray"]
        Tt = self.T_tray() @ make_T(np.eye(3), [0, 0, -t["thickness"] / 2000])
        markers.append(self.box_marker("tray", 0, Tt, (t["length"], t["width"], t["thickness"]), (0.55, 0.57, 0.60)))

        # 出餐盤
        pl = self.scene["plate"]
        markers.append(self.cyl_marker("plate", 0, self.T_plate() @ make_T(np.eye(3), [0, 0, -pl["thickness"] / 2000]),
                                       pl["diameter"], pl["thickness"], (0.93, 0.93, 0.90)))

        # 工具：三角形直接畫在各手臂的 link6 座標上。
        # stamp = 0 + frame_locked：RViz 用最新的 TF 畫、手臂動時自動跟著走。
        # （stamp 用「現在」的話，link6 的 TF 常常還沒到，RViz 那一格就不畫 → 閃爍）
        # 外形沒變時每秒才重送一次（夾爪開合時外形每格都變，就每格送）。
        t_now = self.get_clock().now().nanoseconds * 1e-9
        sent = getattr(self, "_tool_sent", {})
        self._tool_sent = sent
        for i, p in enumerate(ARMS):
            key = self.tool_key(p)
            if sent.get(p, (None, 0.0))[0] == key and t_now - sent[p][1] < 1.0:
                continue
            sent[p] = (key, t_now)
            tri = np.concatenate(list(self.tool_geom(p)[0].values()))
            m = Marker()
            m.header.frame_id = f"{p}link6"
            m.frame_locked = True
            m.ns, m.id, m.type, m.action = "tool", i, Marker.TRIANGLE_LIST, Marker.ADD
            m.pose.orientation.w = 1.0
            m.scale.x = m.scale.y = m.scale.z = 1.0
            m.color.r, m.color.g, m.color.b, m.color.a = 0.78, 0.80, 0.84, 1.0
            m.points = [Point(x=float(x), y=float(y), z=float(z)) for x, y, z in tri.reshape(-1, 3)]
            markers.append(m)

        # 肉排：上下兩半。放上煎台後朝下（正在煎）的那面是深褐色，翻面後會朝上；生的兩面都是肉色
        raw_rgb, cooked_rgb = (0.85, 0.45, 0.42), (0.40, 0.20, 0.08)
        pp = self.scene["patty"]
        for i in range(2):
            if self.patty is None:
                markers.append(self.delete_marker("patty", i))
                continue
            sign = -1 if i == 0 else 1
            rgb = raw_rgb if (i == 1 or self.patty.get("raw")) else cooked_rgb
            T = self.patty["T"] @ make_T(np.eye(3), [0, 0, sign * pp["thickness"] / 4000])
            markers.append(self.cyl_marker("patty", i, T, pp["diameter"], pp["thickness"] / 2, rgb))
        # 托盤上的生肉排（多送幾個 DELETE，片數改少時舊的會消失）
        for i in range(max(len(self.tray_slots), 12)):
            if i < len(self.tray_slots) and self.tray_slots[i]:
                markers.append(self.cyl_marker("tray_patty", i, self.tray_slot_T(i),
                                               pp["diameter"], pp["thickness"], raw_rgb))
            else:
                markers.append(self.delete_marker("tray_patty", i))
        self.mk_pub.publish(MarkerArray(markers=markers))

    @staticmethod
    def _posed_marker(ns, i, mtype, T, scale, rgb):
        m = Marker()
        m.header.frame_id = "world"
        m.ns, m.id, m.type, m.action = ns, i, mtype, Marker.ADD
        m.pose.position.x, m.pose.position.y, m.pose.position.z = (float(v) for v in T[:3, 3])
        qx, qy, qz, qw = mat_to_quat(T[:3, :3])
        m.pose.orientation.x, m.pose.orientation.y, m.pose.orientation.z, m.pose.orientation.w = qx, qy, qz, qw
        m.scale.x, m.scale.y, m.scale.z = scale
        m.color.r, m.color.g, m.color.b = rgb
        m.color.a = 1.0
        return m

    def cyl_marker(self, ns, i, T, diameter_mm, height_mm, rgb):
        return self._posed_marker(ns, i, Marker.CYLINDER, T,
                                  (diameter_mm / 1000, diameter_mm / 1000, height_mm / 1000), rgb)

    def box_marker(self, ns, i, T, size_mm, rgb):
        return self._posed_marker(ns, i, Marker.CUBE, T, tuple(v / 1000 for v in size_mm), rgb)

    @staticmethod
    def delete_marker(ns, i):
        m = Marker()
        m.header.frame_id = "world"
        m.ns, m.id, m.action = ns, i, Marker.DELETE
        return m

    @staticmethod
    def tf_msg(stamp, parent, child, T):
        m = TransformStamped()
        m.header.stamp = stamp
        m.header.frame_id = parent
        m.child_frame_id = child
        m.transform.translation.x, m.transform.translation.y, m.transform.translation.z = (float(v) for v in T[:3, 3])
        qx, qy, qz, qw = mat_to_quat(T[:3, :3])
        m.transform.rotation.x, m.transform.rotation.y, m.transform.rotation.z, m.transform.rotation.w = qx, qy, qz, qw
        return m


# ---------------------------------------------------------------- 介面
class Panel(QWidget):
    def __init__(self, node):
        super().__init__()
        self.node = node
        self.arm = ARMS[0]
        self.mode = "JOINT"
        self.active = None   # (idx, direction) 按住中的按鈕
        # 標題列由 WSLg 繪製，用不到我們載入的中文字型，所以用英文
        self.setWindowTitle("SmartCook V2 Jog Panel")
        # 內容放進可捲動區域：螢幕不夠高時可以捲
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        lay = QVBoxLayout(content)

        # 手臂 / 座標模式
        sel = QHBoxLayout()
        self.arm_group = QButtonGroup(self)
        for p in ARMS:
            b = QRadioButton(ARM_NAMES[p])
            b.setChecked(p == self.arm)
            b.toggled.connect(lambda on, p=p: on and self.set_arm(p))
            self.arm_group.addButton(b)
            sel.addWidget(b)
        sel.addSpacing(20)
        self.mode_group = QButtonGroup(self)
        for m in MODES:
            b = QPushButton(MODE_NAMES[m])
            b.setCheckable(True)
            b.setChecked(m == self.mode)
            b.clicked.connect(lambda _, m=m: self.set_mode(m))
            self.mode_group.addButton(b)
            sel.addWidget(b)
        lay.addLayout(sel)

        # 速度
        sp = QHBoxLayout()
        sp.addWidget(QLabel("速度"))
        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(1, 100)
        self.speed.setValue(30)
        self.speed_lbl = QLabel("30%")
        self.speed.valueChanged.connect(lambda v: self.speed_lbl.setText(f"{v}%"))
        sp.addWidget(self.speed)
        sp.addWidget(self.speed_lbl)
        lay.addLayout(sp)

        # 吋動按鈕
        grid = QGridLayout()
        self.axis_lbls = []
        for i in range(6):
            lbl = QLabel()
            lbl.setMinimumWidth(60)
            self.axis_lbls.append(lbl)
            minus, plus = QPushButton("−"), QPushButton("+")
            for b, d in ((minus, -1), (plus, 1)):
                b.setMinimumHeight(28)
                b.pressed.connect(lambda i=i, d=d: self.start(i, d))
                b.released.connect(self.stop)
            grid.addWidget(lbl, i, 0)
            grid.addWidget(minus, i, 1)
            grid.addWidget(plus, i, 2)
        lay.addLayout(grid)

        home = QPushButton("回原點（全部軸 0°）")
        home.clicked.connect(self.go_home)
        lay.addWidget(home)

        # 軸角度直接輸入
        j_box = QGroupBox("軸角度輸入（deg，所選手臂）")
        jl = QGridLayout(j_box)
        self.joint_spins = []
        for i in range(6):
            s = QDoubleSpinBox()
            s.setDecimals(1)
            s.setSingleStep(1.0)
            s.setKeyboardTracking(False)
            jl.addWidget(QLabel(f"JT{i + 1}"), i // 3, (i % 3) * 2)
            jl.addWidget(s, i // 3, (i % 3) * 2 + 1)
            self.joint_spins.append(s)
        read_btn = QPushButton("讀取目前角度")
        read_btn.clicked.connect(self.load_joint_inputs)
        go_btn = QPushButton("移動到輸入角度")
        go_btn.clicked.connect(self.go_to_inputs)
        stop_btn = QPushButton("停止")
        stop_btn.clicked.connect(self.stop)
        jl.addWidget(read_btn, 2, 0, 1, 2)
        jl.addWidget(go_btn, 2, 2, 1, 2)
        jl.addWidget(stop_btn, 2, 4, 1, 2)
        lay.addWidget(j_box)
        self.target = None          # 移動到輸入角度時的目標（rad）
        self.load_joint_inputs()

        # 目前位置
        self.pose_lbl = QLabel()
        # 等寬字放數字，中文字退回到載入的中文字型
        self.pose_lbl.setStyleSheet(f"font-family: 'DejaVu Sans Mono', '{QApplication.font().family()}';")
        self.pose_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.pose_lbl)
        self.msg_lbl = QLabel()
        self.msg_lbl.setStyleSheet("color: #d08000;")
        lay.addWidget(self.msg_lbl)

        # 各手臂的工具
        t_box = QGroupBox("工具（TCP：平鏟 = 鏟尖中心、底面；夾爪 = 兩指指尖中心）")
        tl = QHBoxLayout(t_box)
        for arm in ARMS:
            tl.addWidget(QLabel(ARM_NAMES[arm]))
            cb = QComboBox()
            for k, name in TOOL_NAMES.items():
                cb.addItem(name, k)
            cb.setCurrentIndex(list(TOOL_NAMES).index(self.node.tool(arm)))
            cb.currentIndexChanged.connect(lambda i, arm=arm, cb=cb: self.set_tool(arm, cb.itemData(i)))
            tl.addWidget(cb)
        lay.addWidget(t_box)

        # 平鏟
        s_box = QGroupBox("平鏟（mm / deg）")
        sl = QGridLayout(s_box)
        r1, r2, r3 = QHBoxLayout(), QHBoxLayout(), QHBoxLayout()
        self.spin(r1, "spatula", "blade_width", "鏟面寬", 30, 400)
        self.spin(r1, "spatula", "blade_length", "鏟面長", 30, 400)
        self.spin(r1, "spatula", "blade_thickness", "厚", 0.5, 20)
        self.spin(r2, "spatula", "bend_angle", "彎角", 0, 90)
        self.spin(r2, "spatula", "shaft_length", "把手長", 0, 600)
        self.spin(r2, "spatula", "shaft_diameter", "把手徑", 5, 80)
        self.spin(r3, "spatula", "mount_diameter", "法蘭座徑", 20, 200)
        self.spin(r3, "spatula", "mount_thickness", "法蘭座厚", 1, 100)
        export = QPushButton("匯出 STL")
        export.clicked.connect(lambda: self.msg_lbl.setText(self.node.export_tool_stl("spatula")))
        r3.addWidget(export)
        for i, r in enumerate((r1, r2, r3)):
            sl.addLayout(r, i, 0)
        lay.addWidget(s_box)

        # 夾爪
        gr_box = QGroupBox("夾爪（平行雙指，mm）")
        grl = QGridLayout(gr_box)
        r1, r2, r3 = QHBoxLayout(), QHBoxLayout(), QHBoxLayout()
        self.spin(r1, "gripper", "body_length", "本體長", 50, 400)
        self.spin(r1, "gripper", "body_depth", "本體寬", 20, 200)
        self.spin(r1, "gripper", "body_height", "本體高", 10, 200)
        self.spin(r2, "gripper", "finger_length", "夾指長", 20, 300)
        self.spin(r2, "gripper", "finger_width", "夾指寬", 10, 200)
        self.spin(r2, "gripper", "finger_thickness", "夾指厚", 1, 30)
        self.spin(r3, "gripper", "max_open", "最大張開", 20, 380, self.reset_grippers)
        self.spin(r3, "gripper", "mount_diameter", "法蘭座徑", 20, 200)
        self.spin(r3, "gripper", "mount_thickness", "法蘭座厚", 1, 100)
        export_g = QPushButton("匯出 STL")
        export_g.clicked.connect(lambda: self.msg_lbl.setText(self.node.export_tool_stl("gripper")))
        r3.addWidget(export_g)
        for i, r in enumerate((r1, r2, r3)):
            grl.addLayout(r, i, 0)
        lay.addWidget(gr_box)

        # 煎台
        g_box = QGroupBox("煎台（world，mm / deg）")
        gl = QGridLayout(g_box)
        row = QHBoxLayout()
        self.spin(row, "griddle", "x", "X", -3000, 3000, self.follow_griddle)
        self.spin(row, "griddle", "y", "Y", -3000, 3000, self.follow_griddle)
        self.spin(row, "griddle", "z", "Z 頂面", 0, 2500, self.follow_griddle)
        self.spin(row, "griddle", "yaw", "旋轉", -180, 180, self.follow_griddle)
        gl.addLayout(row, 0, 0)
        row2 = QHBoxLayout()
        self.spin(row2, "griddle", "length", "長", 50, 3000)
        self.spin(row2, "griddle", "width", "寬", 50, 3000)
        self.spin(row2, "griddle", "thickness", "厚", 5, 500)
        gl.addLayout(row2, 1, 0)
        lay.addWidget(g_box)

        # 碰撞檢查
        c_box = QGroupBox("碰撞檢查（手臂 vs 煎台、立柱、另一支手臂、地面）")
        cl = QHBoxLayout(c_box)
        self.coll_chk = QCheckBox("啟用")
        self.coll_chk.setChecked(bool(self.node.scene["collision"]["enabled"]))
        self.coll_chk.toggled.connect(lambda on: self.node.scene["collision"].__setitem__("enabled", on))
        cl.addWidget(self.coll_chk)
        self.spin(cl, "collision", "margin", "安全距離 mm", 0, 200)
        self.coll_lbl = QLabel()
        cl.addWidget(self.coll_lbl)
        lay.addWidget(c_box)

        # 取料托盤
        tr_box = QGroupBox("取料托盤（world，頂面中心；mm / deg）")
        trl = QGridLayout(tr_box)
        r1, r2 = QHBoxLayout(), QHBoxLayout()
        self.spin(r1, "tray", "x", "X", -3000, 3000)
        self.spin(r1, "tray", "y", "Y", -3000, 3000)
        self.spin(r1, "tray", "z", "Z 頂面", 0, 2500)
        self.spin(r1, "tray", "yaw", "旋轉", -180, 180)
        self.spin(r2, "tray", "length", "長", 50, 2000)
        self.spin(r2, "tray", "width", "寬", 50, 2000)
        self.spin(r2, "tray", "thickness", "厚", 2, 200)
        self.spin(r2, "tray", "count", "片數", 1, 12, lambda v: self.node.refill_tray())
        self.spin(r2, "tray", "spacing", "間距", 30, 500)
        trl.addLayout(r1, 0, 0)
        trl.addLayout(r2, 1, 0)
        lay.addWidget(tr_box)

        # 出餐盤
        pl_box = QGroupBox("出餐盤（world，頂面中心；mm）")
        pll = QHBoxLayout(pl_box)
        self.spin(pll, "plate", "x", "X", -3000, 3000)
        self.spin(pll, "plate", "y", "Y", -3000, 3000)
        self.spin(pll, "plate", "z", "Z 頂面", 0, 2500)
        self.spin(pll, "plate", "diameter", "直徑", 100, 600)
        self.spin(pll, "plate", "thickness", "厚", 2, 100)
        lay.addWidget(pl_box)

        # 肉排：取料、翻面、上菜
        f_box = QGroupBox("肉排：取料 → 放上煎台 → 翻面 → 上菜（肉排位置用煎台座標，mm / deg）")
        fl = QVBoxLayout(f_box)
        r1, r2, r3, r4 = QHBoxLayout(), QHBoxLayout(), QHBoxLayout(), QHBoxLayout()
        place = self.follow_griddle      # 改肉排位置 / 尺寸：肉排在煎台上就直接移過去
        self.spin(r1, "patty", "x", "煎台上位置 X", -1500, 1500, place)
        self.spin(r1, "patty", "y", "Y", -1500, 1500, place)
        self.spin(r1, "patty", "diameter", "直徑", 30, 300, place)
        self.spin(r1, "patty", "thickness", "厚", 3, 60, place)
        self.spin(r2, "patty", "approach", "鏟入方向", -180, 180)
        self.auto_dir = QCheckBox("到不了就自動換方向")
        self.auto_dir.setChecked(True)
        r2.addWidget(self.auto_dir)
        self.spin(r2, "patty", "lift", "抬高", 30, 400)
        self.task_btns = []
        for text, kinds, row in (("完整流程：取料 → 煎 → 翻面 → 上菜", ["full"], r3),
                                 ("取料放上煎台", ["pick"], r3), ("翻面", ["flip"], r3), ("上菜", ["serve"], r3)):
            b = QPushButton(text)
            b.clicked.connect(lambda _, k=kinds: self.start_task(k))
            row.addWidget(b)
            self.task_btns.append(b)
        reset_btn = QPushButton("重設（清空煎台和盤子、補滿托盤）")
        reset_btn.clicked.connect(self.reset_all)
        direct_btn = QPushButton("從煎台開始（直接放一片）")
        direct_btn.clicked.connect(self.place_patty)
        stop_btn = QPushButton("停止")
        stop_btn.clicked.connect(self.stop)
        for b in (reset_btn, direct_btn, stop_btn):
            r4.addWidget(b)
        for r in (r1, r2, r3, r4):
            fl.addLayout(r)
        lay.addWidget(f_box)
        self.task_state = None     # None / "planning" / "running"
        self.task_queue = []
        self.plan_result = None
        self.plan_token = None

        save = QPushButton("儲存設定（工具 + 煎台 + 托盤 + 碰撞 + 肉排）")
        save.clicked.connect(lambda: self.msg_lbl.setText(self.node.save_scene()))
        lay.addWidget(save)

        self.update_axis_labels()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(int(DT * 1000))

    def spin(self, layout, group, key, label, lo, hi, on_change=None):
        layout.addWidget(QLabel(label))
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(1)
        s.setSingleStep({"yaw": 1.0, "bend_angle": 1.0, "blade_thickness": 0.5, "thickness": 1.0}.get(key, 5.0))
        s.setValue(self.node.scene[group][key])

        def changed(v, g=group, k=key):
            self.node.scene[g][k] = v
            if on_change:
                on_change(v)
        s.valueChanged.connect(changed)
        layout.addWidget(s)

    def follow_griddle(self, _v):
        """煎台移動 / 改肉排設定時，放在煎台上的肉排跟著移到設定位置。"""
        pt = self.node.patty
        if (getattr(self, "task_state", None) is None and pt is not None and pt["mode"] == "rest"
                and pt.get("where") != "plate"):
            self.node.reset_patty()

    def set_tool(self, arm, tool):
        self.stop()
        self.node.scene["tools"][arm.rstrip("_")] = tool
        self.node.grip_open[arm] = self.node.scene["gripper"]["max_open"]
        self.msg_lbl.setText(f"{ARM_NAMES[arm]}換成{TOOL_NAMES[tool]}")

    def reset_grippers(self, _v=None):
        for arm in ARMS:
            self.node.grip_open[arm] = self.node.scene["gripper"]["max_open"]

    def place_patty(self):
        self.stop()
        self.node.reset_patty()
        self.msg_lbl.setText("煎台上放了一片肉排（從煎台開始）")

    def reset_all(self):
        self.stop()
        self.node.patty = None
        self.node.refill_tray()
        self.reset_grippers()
        self.msg_lbl.setText("煎台和出餐盤已清空、托盤已補滿")

    def task_arm(self, kind):
        """翻面：裝平鏟的手臂（兩支都是時用目前選的那支）。
        取料 / 上菜 / 完整流程：兩支都是平鏟時回傳 "both"（左鏟端、右鏟刮 / 擋）；否則用裝夾爪的那支。"""
        spat = [a for a in ARMS if self.node.tool(a) == "spatula"]
        if kind == "flip":
            return (self.arm if self.arm in spat else spat[0]) if spat else None
        if len(spat) == len(ARMS):
            return "both"
        grip = [a for a in ARMS if self.node.tool(a) == "gripper"]
        return grip[0] if grip else None

    def start_task(self, kinds):
        if self.task_state is not None:
            return
        self.stop()
        self.task_queue = list(kinds)
        for b in self.task_btns:
            b.setEnabled(False)
        self.plan_next()

    def plan_next(self):
        kind = self.task_queue.pop(0)
        arm = self.task_arm(kind)
        if arm is None:
            self.end_task("翻面要有一支手臂裝平鏟" if kind == "flip"
                          else "取料要兩支都裝平鏟，或一支裝夾爪：在「工具」欄換")
            return
        self.task_state = "planning"
        self.plan_result = None
        name = {"flip": "翻面", "pick": "取料", "full": "取料 → 翻面 → 上菜", "serve": "上菜"}[kind]
        who = (f"{ARM_SIDE[PICKUP_CARRIER]}鏟接、{ARM_SIDE[PICKUP_SCRAPER]}鏟刮" if arm == "both"
               else ARM_NAMES[arm])
        self.msg_lbl.setText(f"規劃{name}路徑中（{who}，逆運動學 + 碰撞檢查，完整流程約 1～2 分鐘）…")
        q0 = {a: self.node.q[a].copy() for a in ARMS}
        theta, auto = self.node.scene["patty"]["approach"], self.auto_dir.isChecked()
        self.plan_token = token = object()

        def work():
            try:
                if kind == "flip":
                    res = self.node.plan_flip(arm, q0[arm], theta, auto)
                elif arm == "both" and kind == "serve":
                    res = self.node.plan_serve(PICKUP_CARRIER, PICKUP_SCRAPER, q0[PICKUP_CARRIER], q0[PICKUP_SCRAPER])
                elif arm == "both":
                    full = kind == "full"
                    res = self.node.plan_two_spatula(PICKUP_CARRIER, PICKUP_SCRAPER, q0[PICKUP_CARRIER],
                                                     q0[PICKUP_SCRAPER], then_flip=full, then_serve=full)
                elif kind in ("full", "serve"):
                    res = "完整流程、上菜要兩支手臂都裝平鏟"
                else:
                    res = self.node.plan_pick_place(arm, q0[arm])
            except Exception as e:   # noqa: BLE001  顯示在面板上，不要讓執行緒默默結束
                res = f"規劃失敗：{e}"
            self.plan_result = (token, PICKUP_CARRIER if arm == "both" else arm, q0, res)
        threading.Thread(target=work, daemon=True).start()

    def end_task(self, msg):
        self.task_state = None
        self.task_queue = []
        for b in self.task_btns:
            b.setEnabled(True)
        self.msg_lbl.setText(msg)

    def set_arm(self, arm):
        self.arm = arm
        self.stop()
        self.load_joint_inputs()

    def load_joint_inputs(self):
        """輸入框的範圍設成所選手臂的軸極限，數值填目前角度。"""
        c = self.node.chains[self.arm]
        for i, s in enumerate(self.joint_spins):
            s.setRange(math.degrees(c.lower[i]), math.degrees(c.upper[i]))
            s.setValue(math.degrees(self.node.q[self.arm][i]))

    def go_to_inputs(self):
        self.stop()
        self.target = np.radians([s.value() for s in self.joint_spins])
        self.target_arm = self.arm

    def set_mode(self, mode):
        self.mode = mode
        self.stop()
        self.update_axis_labels()

    def update_axis_labels(self):
        names = ([f"JT{i + 1}" for i in range(6)] if self.mode == "JOINT"
                 else ["X", "Y", "Z", "Rx", "Ry", "Rz"])
        for lbl, n in zip(self.axis_lbls, names):
            lbl.setText(n)

    def start(self, idx, direction):
        self.stop()
        self.active = (idx, direction)

    def stop(self):
        """停止所有動作（吋動、移動到輸入角度、翻面；規劃中的結果會丟掉）。"""
        self.active = None
        self.target = None
        if getattr(self, "task_state", None) is not None:
            stopped = self.node.flip is not None
            self.node.flip = None
            self.plan_token = None
            self.end_task("動作已停止" if stopped else "已取消規劃")

    def go_home(self):
        self.stop()
        msgs = [self.node.try_set(p, np.zeros_like(self.node.q[p])) for p in ARMS]
        self.msg_lbl.setText("；".join(m for m in msgs if m))

    def tick(self):
        if self.active:
            idx, d = self.active
            s = self.speed.value() / 100
            if self.mode == "JOINT":
                msg = self.node.jog_joint(self.arm, idx, d, s)
            else:
                msg = self.node.jog_cart(self.arm, self.mode, idx, d, s)
            self.msg_lbl.setText(msg)
        elif self.target is not None:
            msg, done = self.node.move_toward(self.target_arm, self.target, self.speed.value() / 100)
            self.msg_lbl.setText(msg)
            if done:
                self.target = None
        elif self.task_state == "planning" and self.plan_result and self.plan_result[0] is self.plan_token:
            _, arm, q0, res = self.plan_result
            self.plan_result = None
            if isinstance(res, str):
                self.end_task(res)
            elif any(not np.array_equal(self.node.q[a], q0[a]) for a in ARMS):
                self.end_task("規劃期間手臂動過了，請重新按一次")
            else:
                self.node.start_motion(arm, res)
                self.task_state = "running"
                self.task_info = f"（鏟入方向 {res['theta']:.0f}°）" if "theta" in res else ""
        elif self.task_state == "running":
            msg, done = self.node.flip_tick(self.speed.value() / 100)
            self.msg_lbl.setText(msg)
            if done:
                if self.task_queue:
                    self.plan_next()
                else:
                    self.end_task(msg + self.task_info)
        if self.node.flip is None:
            # 翻面停止後：在鏟子上的肉排跟著手臂、正在掉的讓它落地
            self.node.update_patty(DT * self.speed.value() / 100)
        hit = self.node.colliding()
        self.coll_lbl.setText("⚠ 干涉中" if hit else "OK")
        self.coll_lbl.setStyleSheet("color: red; font-weight: bold;" if hit else "color: green;")
        self.node.publish(hit)
        self.show_pose()
        rclpy.spin_once(self.node, timeout_sec=0)

    def show_pose(self):
        c = self.node.chains[self.arm]
        q = self.node.q[self.arm]
        T_base, Tt, _, _ = c.fk(q, self.node.T_tcp(self.arm))
        lines = ["軸 (deg)  " + "  ".join(f"JT{i + 1}:{math.degrees(v):7.1f}" for i, v in enumerate(q))]

        def fmt(name, T):
            o, a, t = mat_to_oat(T[:3, :3])
            x, y, z = T[:3, 3] * 1000
            return f"{name:<6}X{x:8.1f} Y{y:8.1f} Z{z:8.1f}   O{o:7.1f} A{a:7.1f} T{t:7.1f}"

        lines.append(fmt("基座", np.linalg.inv(T_base) @ Tt))
        lines.append(fmt("世界", Tt))
        lines.append(fmt("煎台", np.linalg.inv(self.node.T_griddle()) @ Tt))
        self.pose_lbl.setText("\n".join(lines))


def setup_cjk_font(app, node):
    """系統已有中文字型就不動；沒有的話載入 CJK_FONT_FILES 裡第一個找得到的。"""
    if any(QFontDatabase().families(QFontDatabase.TraditionalChinese)):
        return
    for path in CJK_FONT_FILES:
        if not os.path.exists(path):
            continue
        fid = QFontDatabase.addApplicationFont(path)
        families = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        if families:
            app.setFont(QFont(families[0], app.font().pointSize()))
            node.get_logger().info(f"中文字型：{families[0]}（{path}）")
            return
    node.get_logger().warn("找不到中文字型，面板上的中文會顯示成方塊；可安裝 fonts-noto-cjk")


def main():
    rclpy.init(args=sys.argv)
    node = JogNode()
    app = QApplication(sys.argv)
    setup_cjk_font(app, node)
    panel = Panel(node)
    # 視窗大小：內容高度，但不超過螢幕可用高度（超過就捲動）
    avail = app.primaryScreen().availableGeometry()
    panel.resize(min(940, avail.width() - 40), min(1100, avail.height() - 60))
    panel.show()
    code = app.exec_()
    node.destroy_node()
    rclpy.shutdown()
    sys.exit(code)


if __name__ == "__main__":
    main()
