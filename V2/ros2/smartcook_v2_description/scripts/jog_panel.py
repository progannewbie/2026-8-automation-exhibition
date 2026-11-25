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

煎台與 TCP 偏移存在 scene_file（預設 config/scene.yaml），面板上按「儲存設定」寫回。

碰撞檢查
  每支手臂 link1～link6 的 3D 模型表面每約 5 mm 取一點，檢查有沒有點進入
  「煎台方塊 + 安全距離」或低於地面。會撞到的吋動直接拒絕；
  若已經在干涉中（例如把煎台移到手臂上），只允許讓干涉變少的動作，方便退出。
  工具（平鏟）還沒建模，不在檢查範圍內。
"""
import math
import os
import sys
import xml.etree.ElementTree as ET

import numpy as np
import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import TransformStamped
from python_qt_binding.QtCore import Qt, QTimer
from python_qt_binding.QtGui import QFont, QFontDatabase
from python_qt_binding.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QRadioButton, QSlider, QVBoxLayout, QWidget,
)
from rclpy.node import Node
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


def sample_stl(path, scale, spacing):
    """讀 STL（binary），在每個三角形表面均勻取點，回傳 (N, 3)，單位 m。"""
    with open(path, "rb") as f:
        data = f.read()
    n = int.from_bytes(data[80:84], "little")
    if 84 + 50 * n != len(data):
        raise ValueError(f"只支援 binary STL：{path}")
    rec = np.frombuffer(data[84:], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    tri = rec["v"].astype(np.float64) * scale            # (n, 3, 3)
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

        # 會動的連桿（link1～link6）表面取樣點，座標在各自 link frame
        self.points = {}
        links = {l.get("name"): l for l in root.findall("link")}
        for _, ax, child in self.elems:
            if ax is None:
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
            self.points[child] = P

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

    def world_points(self, q):
        """所有會動連桿的取樣點（world 座標），回傳 {link: (N, 3)}。"""
        link_T = self.fk(q, np.eye(4), links=True)[4]
        return {l: P @ link_T[l][:3, :3].T + link_T[l][:3, 3] for l, P in self.points.items()}

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

        self.scene_file = self.get_parameter("scene_file").value
        self.scene = self.load_scene()

        self.js_pub = self.create_publisher(JointState, "joint_states", 10)
        self.mk_pub = self.create_publisher(MarkerArray, "smartcook_scene", 10)
        self.tf_pub = TransformBroadcaster(self)

    # ---- 場景設定
    def load_scene(self):
        default = {
            "griddle": {"x": 0.0, "y": -600.0, "z": 850.0, "yaw": 0.0,
                        "length": 600.0, "width": 400.0, "thickness": 60.0},
            "tcp": {"x": 0.0, "y": 0.0, "z": 0.0},
            "collision": {"enabled": True, "margin": 10.0},
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

    def T_tcp(self):
        t = self.scene["tcp"]
        return make_T(np.eye(3), [t["x"] / 1000, t["y"] / 1000, t["z"] / 1000])

    def T_griddle(self):
        g = self.scene["griddle"]
        return make_T(rpy_to_mat(0, 0, math.radians(g["yaw"])), [g["x"] / 1000, g["y"] / 1000, g["z"] / 1000])

    # ---- 碰撞
    def interference(self, arm, q):
        """回傳 (干涉深度總和 m, 最嚴重的連桿, 對象)。0 = 沒有干涉。

        對象：煎台（方塊加安全距離）、地面（z < 0）。
        """
        g = self.scene["griddle"]
        m = self.scene["collision"]["margin"] / 1000
        hx, hy = g["length"] / 2000 + m, g["width"] / 2000 + m
        z_lo, z_hi = -g["thickness"] / 1000 - m, m
        Tg = self.T_griddle()
        total, worst, worst_link, what = 0.0, 0.0, "", ""
        for link, P in self.chains[arm].world_points(q).items():
            L = (P - Tg[:3, 3]) @ Tg[:3, :3]          # 轉到煎台座標
            depth = np.minimum.reduce([hx - L[:, 0], hx + L[:, 0], hy - L[:, 1], hy + L[:, 1],
                                       z_hi - L[:, 2], L[:, 2] - z_lo])
            d = depth[depth > 0]
            floor = -P[:, 2][P[:, 2] < 0]
            for arr, name in ((d, "煎台"), (floor, "地面")):
                if arr.size:
                    total += float(arr.sum())
                    if arr.max() > worst:
                        worst, worst_link, what = float(arr.max()), link, name
        return total, worst_link, what

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
            return f"干涉中（{link.replace(arm, '')} 碰到{what}），請往外移"
        return f"停止：{link.replace(arm, '')} 會碰到{what}"

    def colliding(self):
        return any(self.interference(p, self.q[p])[0] > 0 for p in ARMS)

    # ---- 吋動
    def jog_joint(self, arm, idx, direction, speed):
        c = self.chains[arm]
        q = self.q[arm].copy()
        q[idx] += direction * MAX_JNT * speed * DT
        if q[idx] < c.lower[idx] or q[idx] > c.upper[idx]:
            return f"JT{idx + 1} 到達極限"
        return self.try_set(arm, q)

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
        self.mk_pub.publish(MarkerArray(markers=[body, top, label]))

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
        lay = QVBoxLayout(self)

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
                b.setMinimumHeight(34)
                b.pressed.connect(lambda i=i, d=d: self.start(i, d))
                b.released.connect(self.stop)
            grid.addWidget(lbl, i, 0)
            grid.addWidget(minus, i, 1)
            grid.addWidget(plus, i, 2)
        lay.addLayout(grid)

        home = QPushButton("回原點（全部軸 0°）")
        home.clicked.connect(self.go_home)
        lay.addWidget(home)

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
        tcp_box = QGroupBox("工具座標 TCP（相對 link6 法蘭，mm）")
        tl = QHBoxLayout(tcp_box)
        self.spin(tl, "tcp", "x", "X", -500, 500)
        self.spin(tl, "tcp", "y", "Y", -500, 500)
        self.spin(tl, "tcp", "z", "Z", -500, 500)
        lay.addWidget(tcp_box)

        # 煎台
        g_box = QGroupBox("煎台（world，mm / deg）")
        gl = QGridLayout(g_box)
        row = QHBoxLayout()
        self.spin(row, "griddle", "x", "X", -3000, 3000)
        self.spin(row, "griddle", "y", "Y", -3000, 3000)
        self.spin(row, "griddle", "z", "Z 頂面", 0, 2500)
        self.spin(row, "griddle", "yaw", "旋轉", -180, 180)
        gl.addLayout(row, 0, 0)
        row2 = QHBoxLayout()
        self.spin(row2, "griddle", "length", "長", 50, 3000)
        self.spin(row2, "griddle", "width", "寬", 50, 3000)
        self.spin(row2, "griddle", "thickness", "厚", 5, 500)
        gl.addLayout(row2, 1, 0)
        lay.addWidget(g_box)

        # 碰撞檢查
        c_box = QGroupBox("碰撞檢查（手臂 vs 煎台、地面）")
        cl = QHBoxLayout(c_box)
        self.coll_chk = QCheckBox("啟用")
        self.coll_chk.setChecked(bool(self.node.scene["collision"]["enabled"]))
        self.coll_chk.toggled.connect(lambda on: self.node.scene["collision"].__setitem__("enabled", on))
        cl.addWidget(self.coll_chk)
        self.spin(cl, "collision", "margin", "安全距離 mm", 0, 200)
        self.coll_lbl = QLabel()
        cl.addWidget(self.coll_lbl)
        lay.addWidget(c_box)

        save = QPushButton("儲存設定（煎台 + TCP + 碰撞）")
        save.clicked.connect(lambda: self.msg_lbl.setText(self.node.save_scene()))
        lay.addWidget(save)

        self.update_axis_labels()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(int(DT * 1000))

    def spin(self, layout, group, key, label, lo, hi):
        layout.addWidget(QLabel(label))
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(1)
        s.setSingleStep(5.0 if key != "yaw" else 1.0)
        s.setValue(self.node.scene[group][key])
        s.valueChanged.connect(lambda v, g=group, k=key: self.node.scene[g].__setitem__(k, v))
        layout.addWidget(s)

    def set_arm(self, arm):
        self.arm = arm
        self.stop()

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
        self.active = (idx, direction)

    def stop(self):
        self.active = None

    def go_home(self):
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
    panel.show()
    code = app.exec_()
    node.destroy_node()
    rclpy.shutdown()
    sys.exit(code)


if __name__ == "__main__":
    main()
