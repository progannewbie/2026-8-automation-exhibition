# V2 ROS 2 模擬：底座 + 兩支 RS007L

在 WSL（Ubuntu 24.04 + ROS 2 Jazzy）用 RViz 顯示機器人底座，立柱頂端兩側各側裝一支 Kawasaki RS007L，可以拉滑桿轉動兩支手臂共 12 個關節。

## 第一次安裝

在 Windows 終端機執行（會下載 Kawasaki 官方 RS007L 模型到 WSL 的 `~/smartcook_ws`，並編譯）：

```bash
wsl -d Ubuntu -- bash /mnt/d/smartcook/V2/ros2/setup_wsl.sh
```

## 開啟模擬

```bash
wsl -d Ubuntu -- bash -c "source ~/smartcook_ws/install/setup.bash && ros2 launch smartcook_v2_description display.launch.py"
```

會開兩個視窗：RViz（3D 畫面）和 Joint State Publisher（關節滑桿）。

## 安裝位置

立柱頂端兩側各有一塊 190 × 250 mm 的安裝板（x = ±58 mm，z 1014～1204 mm），RS007L 腳座 190 × 220 mm 剛好對上。
每支手臂的底座朝外（base_link 的 Z 軸垂直安裝板），關節全部歸零時手臂水平往外伸。

| 手臂 | 安裝板 | 關節名稱 |
|---|---|---|
| `right_` | +X 側 | `right_joint1`～`right_joint6` |
| `left_` | -X 側 | `left_joint1`～`left_joint6` |

左右是假設從 -Y 方向看底座，跟實際不同的話再對調。

位置用啟動參數調整（單位 m、rad），兩側對稱一起改：

| 參數 | 預設 | 說明 |
|---|---|---|
| `plate_x` | 0.058 | 安裝板面到立柱中心的距離 |
| `mount_y` | 0.108 | 讓 RS007L 腳座中心對齊安裝板中心（y = 120 mm） |
| `mount_z` | 1.109 | 安裝板中心高度（CAD 座標） |
| `mount_roll` | 0.0 | 手臂在安裝板上繞自己 Z 軸轉的角度 |

例如把手臂在板上轉 90°：

```bash
wsl -d Ubuntu -- bash -c "source ~/smartcook_ws/install/setup.bash && ros2 launch smartcook_v2_description display.launch.py mount_roll:=1.5708"
```

要改預設值，改 [smartcook_v2_description/urdf/smartcook_v2.urdf.xacro](smartcook_v2_description/urdf/smartcook_v2.urdf.xacro) 和 `launch/display.launch.py`（兩邊要一致）。

## 檔案

- `smartcook_v2_description/meshes/robot_base.stl`：底座模型，複製自 `V2/圖檔/robot base.stl`（和 `robot_base.step` 尺寸相同，單位 mm）。底座改版後要重新匯出 STL 並覆蓋這個檔。
- RS007L 模型不在這個 repo：它是 Kawasaki 的 CAD 授權，由 `setup_wsl.sh` 下載到 WSL。
  setup 會拿掉 Kawasaki 巨集裡的 White / Black 材質定義（改由我們的 xacro 定義一次），否則兩支手臂會重複定義、URDF 解析失敗。
