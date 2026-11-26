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

翻面模擬
  煎台上放一塊肉排（兩面不同顏色：底面 = 正在煎的面）。按「開始翻面」：
  先規劃整條路徑（逆運動學 + 每一步碰撞檢查），全部可行才開始動：
  移到肉排旁上方 → 下降貼煎台 → 鏟面往前鏟進肉排底下 → 抬起 → JT6 轉 180° 翻鏟
  → 肉排滑落、翻面落回煎台 → JT6 轉回 → 退回上方。
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
    QApplication, QButtonGroup, QCheckBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout,
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
MODES = ["JOINT", "BASE", "TOOL", "WORLD"]
MODE_NAMES = {"JOINT": "軸", "BASE": "基座", "TOOL": "工具", "WORLD": "世界"}

MAX_LIN = 0.100              # m/s，100% 速度
MAX_ROT = math.radians(30)   # rad/s
MAX_JNT = math.radians(30)   # rad/s
DT = 0.04                    # 吋動更新週期 (s)
SAMPLE_SPACING = 0.005       # 碰撞取樣點間距 (m)，要小於安全距離
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


def part_name(arm, link):
    """訊息用的零件名稱：right_link4 → link4、right_spatula_blade → 鏟面。"""
    name = link.replace(arm, "")
    if name.startswith("spatula_"):
        return SPATULA_PART_NAMES.get(name[len("spatula_"):], name)
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
        self.flip = None           # 執行中的翻面：{"arm", "frames", "i"}
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
            yaml.safe_dump({k: {kk: (bool(vv) if isinstance(vv, bool) else float(vv)) for kk, vv in v.items()}
                            for k, v in self.scene.items()},
                           f, allow_unicode=True, sort_keys=False)
        return f"已儲存：{os.path.realpath(self.scene_file)}"

    def spatula(self):
        """目前尺寸的平鏟：(三角形 {part}, 取樣點 {part}, T_tcp)，尺寸沒變就沿用。"""
        key = tuple(self.scene["spatula"].values())
        if getattr(self, "_spatula_key", None) != key:
            tris, T_tcp = spatula_geometry(self.scene["spatula"])
            pts = {k: sample_triangles(v, SAMPLE_SPACING) for k, v in tris.items()}
            self._spatula = (tris, pts, T_tcp)
            self._spatula_key = key
        return self._spatula

    def T_tcp(self):
        """TCP = 鏟尖（相對 link6）。"""
        return self.spatula()[2]

    def arm_points(self, arm, q, include_base=False):
        """手臂連桿 + 平鏟的取樣點（world），{名稱: (N, 3)}；平鏟零件名稱是 <arm>spatula_<part>。"""
        c = self.chains[arm]
        link_T = c.fk(q, np.eye(4), links=True)[4]
        src = {**c.points, **c.base_points} if include_base else c.points
        out = {l: P @ link_T[l][:3, :3].T + link_T[l][:3, 3] for l, P in src.items()}
        T6 = link_T[f"{arm}link6"]
        for part, P in self.spatula()[1].items():
            out[f"{arm}spatula_{part}"] = P @ T6[:3, :3].T + T6[:3, 3]
        return out

    def export_spatula_stl(self):
        """把目前尺寸的平鏟匯出成 STL（mm，原點在法蘭面中心、Z 朝外），放在 V2/圖檔/。"""
        out_dir = os.path.dirname(os.path.realpath(self.scene_file)) if self.scene_file else os.getcwd()
        v2 = os.path.dirname(os.path.dirname(os.path.dirname(out_dir)))   # .../V2/ros2/<pkg>/config → V2
        if os.path.isdir(os.path.join(v2, "圖檔")):
            out_dir = os.path.join(v2, "圖檔")
        path = os.path.join(out_dir, "spatula.stl")
        tris = np.concatenate(list(self.spatula()[0].values()))
        write_stl(path, tris, scale=1000.0, name=b"SmartCook V2 spatula (mm, flange frame)")
        return f"已匯出：{path}"

    def T_griddle(self):
        g = self.scene["griddle"]
        return make_T(rpy_to_mat(0, 0, math.radians(g["yaw"])), [g["x"] / 1000, g["y"] / 1000, g["z"] / 1000])

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

    def other_arm_tree(self, arm):
        """另一支手臂（含 base_link）目前姿態的 KD-tree，姿態沒變就沿用。"""
        other = ARMS[1] if arm == ARMS[0] else ARMS[0]
        key = (self.q[other].tobytes(), tuple(self.scene["spatula"].values()))
        cached = self._arm_tree.get(other)
        if cached is None or cached[0] != key:
            pts = np.concatenate(list(self.arm_points(other, self.q[other], include_base=True).values()))
            cached = (key, cKDTree(pts))
            self._arm_tree[other] = cached
        return cached[1]

    def interference(self, arm, q, with_other_arm=True):
        """回傳 (干涉深度總和 m, 最嚴重的連桿, 對象)。0 = 沒有干涉。

        對象：煎台（方塊加安全距離）、地面（z < 0）、立柱 / 底座、另一支手臂（含它的平鏟）。
        立柱和手臂是取樣點對取樣點的距離，安全距離至少要比取樣間距大才可靠。
        平鏟對煎台不留安全距離：可以貼在煎台面上，但不能壓進去。
        （把手在彎折處只比鏟面底面高一個鏟面厚度，留安全距離的話鏟面永遠貼不到煎台。）
        """
        g = self.scene["griddle"]
        m = self.scene["collision"]["margin"] / 1000
        m_pts = max(m, 2 * SAMPLE_SPACING)
        other = ARMS[1] if arm == ARMS[0] else ARMS[0]
        key = (arm, q.tobytes(), with_other_arm and self.q[other].tobytes(),
               tuple(g.values()), m, tuple(self.scene["spatula"].values()))
        if key in self._interf_cache:
            return self._interf_cache[key]

        Tg = self.T_griddle()
        arm_tree = self.other_arm_tree(arm) if with_other_arm else None
        total, worst, worst_link, what = 0.0, 0.0, "", ""
        for link, P in self.arm_points(arm, q).items():
            mg = 0.0 if "spatula_" in link else m      # 平鏟可以貼著煎台，手臂要留安全距離
            hx, hy = g["length"] / 2000 + mg, g["width"] / 2000 + mg
            z_lo, z_hi = -g["thickness"] / 1000 - mg, mg
            L = (P - Tg[:3, 3]) @ Tg[:3, :3]          # 轉到煎台座標
            depth = np.minimum.reduce([hx - L[:, 0], hx + L[:, 0], hy - L[:, 1], hy + L[:, 1],
                                       z_hi - L[:, 2], L[:, 2] - z_lo])
            hits = [(depth[depth > 0], "煎台"), (-P[:, 2][P[:, 2] < 0], "地面")]
            for tree, name in ((self.base_tree, "立柱"), (arm_tree, "另一支手臂")):
                if tree is None:
                    continue
                d, _ = tree.query(P, distance_upper_bound=m_pts)
                d = d[np.isfinite(d)]
                hits.append((m_pts - d, name))
            for arr, name in hits:
                if arr.size:
                    total += float(arr.sum())
                    if arr.max() > worst:
                        worst, worst_link, what = float(arr.max()), link, name
        result = (total, worst_link, what)
        if len(self._interf_cache) > 64:
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
        T_tcp = self.T_tcp()
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
    def reset_patty(self):
        """肉排放回設定位置，平放（顏色深的那面朝下）。"""
        p = self.scene["patty"]
        self.patty = {"T": self.T_griddle() @ make_T(np.eye(3), [p["x"] / 1000, p["y"] / 1000,
                                                                  p["thickness"] / 2000]),
                      "mode": "rest"}

    def update_patty(self, dt):
        """跟著平鏟移動、或往下掉；dt 是模擬經過的時間 (s)。"""
        pt = self.patty
        if pt["mode"] == "attached":
            arm = pt["arm"]
            pt["T"] = self.chains[arm].fk(self.q[arm], self.T_tcp())[1] @ pt["rel"]
            if pt["T"][2, 2] * pt["up0"] < 0.0:    # 鏟面翻過 90°：肉排滑落
                self.release_patty()
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
        """肉排放到鏟面上（底面貼鏟面頂面），之後跟著 TCP 走。"""
        Tt = self.chains[arm].fk(self.q[arm], self.T_tcp())[1]
        rel = np.linalg.inv(Tt) @ self.patty["T"]
        # TCP 的 Z 朝下（鏟面底面），肉排中心在鏟面頂面上方半個厚度
        rel[2, 3] = -(self.scene["spatula"]["blade_thickness"] + self.scene["patty"]["thickness"] / 2) / 1000
        T = Tt @ rel
        self.patty = {"T": T, "mode": "attached", "arm": arm, "rel": rel, "up0": 1.0 if T[2, 2] >= 0 else -1.0}

    def release_patty(self):
        """從鏟面滑落：落到煎台面上，朝上的軸改成最接近目前姿態的上 / 下。"""
        T0 = self.patty["T"]
        Tg = self.T_griddle()
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
        self.patty = {"T": T0, "mode": "falling", "t": 0.0, "fall": (T0, T1, max(0.15, math.sqrt(2 * drop / 9.81)))}

    # ---- 逆運動學 / 路徑規劃
    def ik(self, arm, T_goal, q0, iters=200):
        """數值逆運動學（DLS），解不到回傳 None。"""
        c = self.chains[arm]
        T_tcp = self.T_tcp()
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
        T0 = self.chains[arm].fk(q0, self.T_tcp())[1]
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

    def first_hit(self, arm, qs):
        """路徑上第一個會碰撞的點的說明，沒有碰撞回傳 None。"""
        if not self.scene["collision"]["enabled"]:
            return None
        for q in qs:
            tot, link, what = self.interference(arm, q)
            if tot > 0:
                return f"{part_name(arm, link)} 會碰到{what}"
        return None

    def flip_poses(self, theta):
        """鏟入方向 theta（deg，煎台座標）時的關鍵 TCP 姿態（world）。"""
        p = self.scene["patty"]
        Tg = self.T_griddle()
        L = np.linalg.inv(Tg) @ self.patty["T"]
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

    def plan_flip(self, arm, q0, theta0, auto=True):
        """規劃整個翻面動作。成功回傳 {"frames": [(q, 階段, 事件)], "theta"}，失敗回傳原因字串。"""
        p, sp = self.scene["patty"], self.scene["spatula"]
        if sp["blade_length"] < p["diameter"] + 10:
            return f"鏟面長 {sp['blade_length']:.0f} mm 太短，至少要比肉排直徑多 10 mm"
        if self.patty["mode"] != "rest":
            return "肉排不在煎台上，先按「放肉排」"
        cands = [theta0]
        if auto:
            cands += [theta0 + s * k for k in range(30, 181, 30) for s in (1, -1)]
        seen, reasons = set(), []
        for th in cands:
            th = (th + 180) % 360 - 180
            if round(th) in seen:
                continue
            seen.add(round(th))
            res = self._plan_flip_dir(arm, q0, th)
            if isinstance(res, list):
                return {"frames": res, "theta": th}
            reasons.append(f"{th:.0f}°：{res}")
        return "找不到可行的翻面路徑\n" + "\n".join(reasons[:6]) + ("\n…" if len(reasons) > 6 else "")

    def _plan_flip_dir(self, arm, q0, theta):
        c = self.chains[arm]
        poses = self.flip_poses(theta)
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
            down = self.plan_linear(arm, q_pre, poses["down"])
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
                h = self.first_hit(arm, qs)
                if h:
                    hit = f"{name}時{h}"
                    break
            if hit:
                why = hit
                continue
            flip = None
            for qs in flips:
                h = self.first_hit(arm, qs)
                if h is None:
                    flip = qs
                    break
                why = f"翻鏟時{h}"
            if flip is None:
                continue
            # 移到肉排旁：直接走軸，撞到的話先抬到更高再直線下來
            approach = self.plan_joint(q0, q_pre)
            h = self.first_hit(arm, approach)
            if h:
                q_high = self.ik(arm, poses["pre"] @ make_T(np.eye(3), [0, 0, -0.25]), q_pre)   # TCP Z 朝下，-Z = 往上
                to_pre = q_high is not None and self.plan_linear(arm, q_high, poses["pre"])
                approach2 = to_pre and self.plan_joint(q0, q_high) + to_pre
                if not approach2 or self.first_hit(arm, approach2):
                    why = f"移到肉排旁時{h}"
                    continue
                approach = approach2
            frames = [(q, "移到肉排旁", None) for q in approach]
            frames += [(q, "下降", None) for q in down]
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

    def start_flip(self, arm, plan):
        self.flip = {"arm": arm, "frames": plan["frames"], "i": 0.0, "n": 0}

    def flip_tick(self, speed):
        """播放翻面一格，回傳 (訊息, 是否結束)。"""
        f = self.flip
        f["i"] += speed
        while f["n"] < min(int(f["i"]), len(f["frames"])):
            q, phase, ev = f["frames"][f["n"]]
            self.q[f["arm"]] = q
            if ev == "attach":
                self.attach_patty(f["arm"])
            elif ev == "release" and self.patty["mode"] == "attached":
                self.release_patty()
            self.update_patty(DT)
            f["n"] += 1
        if f["n"] >= len(f["frames"]):
            self.update_patty(DT)       # 動作播完，肉排如果還在掉就讓它落地
            if self.patty["mode"] != "falling":
                self.flip = None
                return "翻面完成", True
        phase = f["frames"][max(f["n"] - 1, 0)][1]
        return f"翻面中：{phase}", False

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
            tfs.append(self.tf_msg(now, f"{p}link6", f"{p}tcp", self.T_tcp()))
        self.tf_pub.sendTransform(tfs)

        g = self.scene["griddle"]
        body = Marker()
        body.header.frame_id = "griddle"
        body.header.stamp = now
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

        # 平鏟：三角形直接畫在各手臂的 link6 座標上
        tri = np.concatenate(list(self.spatula()[0].values()))
        pts = [Point(x=float(x), y=float(y), z=float(z)) for x, y, z in tri.reshape(-1, 3)]
        for i, p in enumerate(ARMS):
            s = Marker()
            s.header.frame_id = f"{p}link6"
            s.header.stamp = now
            s.ns, s.id, s.type, s.action = "spatula", i, Marker.TRIANGLE_LIST, Marker.ADD
            s.pose.orientation.w = 1.0
            s.scale.x = s.scale.y = s.scale.z = 1.0
            s.color.r, s.color.g, s.color.b, s.color.a = 0.78, 0.80, 0.84, 1.0
            s.points = pts
            markers.append(s)

        # 肉排：上下兩半不同顏色。一開始朝下（正在煎）的那面是深褐色，翻面後會朝上
        pp = self.scene["patty"]
        h, D = pp["thickness"] / 1000, pp["diameter"] / 1000
        for i, (sign, rgb) in enumerate(((-1, (0.40, 0.20, 0.08)), (1, (0.85, 0.45, 0.42)))):
            T = self.patty["T"] @ make_T(np.eye(3), [0, 0, sign * h / 4])
            m = Marker()
            m.header.frame_id = "world"
            m.header.stamp = now
            m.ns, m.id, m.type, m.action = "patty", i, Marker.CYLINDER, Marker.ADD
            m.pose.position.x, m.pose.position.y, m.pose.position.z = (float(v) for v in T[:3, 3])
            qx, qy, qz, qw = mat_to_quat(T[:3, :3])
            m.pose.orientation.x, m.pose.orientation.y, m.pose.orientation.z, m.pose.orientation.w = qx, qy, qz, qw
            m.scale.x, m.scale.y, m.scale.z = D, D, h / 2
            m.color.r, m.color.g, m.color.b = rgb
            m.color.a = 1.0
            markers.append(m)
        self.mk_pub.publish(MarkerArray(markers=markers))

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

        # 工具座標 (TCP) 偏移
        # 平鏟（兩支手臂同一組尺寸；TCP = 鏟尖）
        s_box = QGroupBox("平鏟（mm / deg，TCP = 鏟尖中心、底面）")
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
        export.clicked.connect(lambda: self.msg_lbl.setText(self.node.export_spatula_stl()))
        r3.addWidget(export)
        for i, r in enumerate((r1, r2, r3)):
            sl.addLayout(r, i, 0)
        lay.addWidget(s_box)

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

        # 翻面模擬
        f_box = QGroupBox("翻面模擬（肉排位置用煎台座標，mm / deg）")
        fl = QVBoxLayout(f_box)
        r1, r2, r3 = QHBoxLayout(), QHBoxLayout(), QHBoxLayout()
        place = self.follow_griddle      # 改肉排位置 / 尺寸：肉排在煎台上就直接移過去
        self.spin(r1, "patty", "x", "肉排 X", -1500, 1500, place)
        self.spin(r1, "patty", "y", "Y", -1500, 1500, place)
        self.spin(r1, "patty", "diameter", "直徑", 30, 300, place)
        self.spin(r1, "patty", "thickness", "厚", 3, 60, place)
        self.spin(r2, "patty", "approach", "鏟入方向", -180, 180)
        self.auto_dir = QCheckBox("到不了就自動換方向")
        self.auto_dir.setChecked(True)
        r2.addWidget(self.auto_dir)
        self.spin(r2, "patty", "lift", "抬高", 30, 400)
        reset_btn = QPushButton("放肉排（回到設定位置）")
        reset_btn.clicked.connect(self.place_patty)
        self.flip_btn = QPushButton("開始翻面")
        self.flip_btn.clicked.connect(self.start_flip)
        stop_flip = QPushButton("停止")
        stop_flip.clicked.connect(self.stop)
        for b in (reset_btn, self.flip_btn, stop_flip):
            r3.addWidget(b)
        for r in (r1, r2, r3):
            fl.addLayout(r)
        lay.addWidget(f_box)
        self.flip_state = None     # None / "planning" / "running"
        self.plan_result = None

        save = QPushButton("儲存設定（煎台 + 平鏟 + 碰撞 + 肉排）")
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
        """煎台移動時，放在煎台上的肉排跟著移到同一個煎台座標位置。"""
        if getattr(self, "flip_state", None) is None and self.node.patty["mode"] == "rest":
            self.node.reset_patty()

    def place_patty(self):
        self.stop()
        self.node.reset_patty()
        self.msg_lbl.setText("肉排已放回設定位置")

    def start_flip(self):
        if self.flip_state is not None:
            return
        self.stop()
        self.flip_state = "planning"
        self.plan_result = None
        self.flip_btn.setEnabled(False)
        self.msg_lbl.setText("規劃翻面路徑中（逆運動學 + 碰撞檢查，約 5～20 秒）…")
        arm, q0 = self.arm, self.node.q[self.arm].copy()
        theta, auto = self.node.scene["patty"]["approach"], self.auto_dir.isChecked()
        self.plan_token = token = object()

        def work():
            try:
                res = self.node.plan_flip(arm, q0, theta, auto)
            except Exception as e:   # noqa: BLE001  顯示在面板上，不要讓執行緒默默結束
                res = f"規劃失敗：{e}"
            self.plan_result = (token, arm, q0, res)
        threading.Thread(target=work, daemon=True).start()

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
        if getattr(self, "flip_state", None) is not None:
            if self.node.flip is not None:
                self.msg_lbl.setText("翻面已停止")
            self.node.flip = None
            self.flip_state = None
            self.flip_btn.setEnabled(True)

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
        elif self.flip_state == "planning" and self.plan_result and self.plan_result[0] is self.plan_token:
            _, arm, q0, res = self.plan_result
            self.plan_result = None
            if isinstance(res, str):
                self.msg_lbl.setText(res)
                self.flip_state = None
                self.flip_btn.setEnabled(True)
            elif not np.array_equal(self.node.q[arm], q0):
                self.msg_lbl.setText("規劃期間手臂動過了，請重新按「開始翻面」")
                self.flip_state = None
                self.flip_btn.setEnabled(True)
            else:
                self.node.start_flip(arm, res)
                self.flip_state = "running"
                self.flip_theta = res["theta"]
        elif self.flip_state == "running":
            msg, done = self.node.flip_tick(self.speed.value() / 100)
            if done:
                msg += f"（鏟入方向 {self.flip_theta:.0f}°）"
                self.flip_state = None
                self.flip_btn.setEnabled(True)
            self.msg_lbl.setText(msg)
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
        T_base, Tt, _, _ = c.fk(q, self.node.T_tcp())
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
