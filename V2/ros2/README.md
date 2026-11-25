# V2 ROS 2 模擬：底座 + RS007L

在 WSL（Ubuntu 24.04 + ROS 2 Jazzy）用 RViz 顯示機器人底座裝上 Kawasaki RS007L，可以拉滑桿轉動 6 個關節。

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

## 調整安裝位置

RS007L 相對底座的位置用啟動參數調整（單位 m、rad），例如轉 90°：

```bash
wsl -d Ubuntu -- bash -c "source ~/smartcook_ws/install/setup.bash && ros2 launch smartcook_v2_description display.launch.py mount_yaw:=1.5708"
```

| 參數 | 預設 | 說明 |
|---|---|---|
| `mount_x` | 0.0 | |
| `mount_y` | 0.108 | 讓 RS007L 腳座中心對齊立柱頂面中心（y = 120 mm） |
| `mount_z` | 1.204 | 立柱頂面高度 |
| `mount_yaw` | 0.0 | 繞 Z 軸旋轉 |

要改預設值，改 [smartcook_v2_description/urdf/smartcook_v2.urdf.xacro](smartcook_v2_description/urdf/smartcook_v2.urdf.xacro) 和 `launch/display.launch.py`。

## 檔案

- `smartcook_v2_description/meshes/robot_base.stl`：底座模型，複製自 `V2/圖檔/robot base.stl`（和 `robot_base.step` 尺寸相同，單位 mm）。底座改版後要重新匯出 STL 並覆蓋這個檔。
- RS007L 模型不在這個 repo：它是 Kawasaki 的 CAD 授權，由 `setup_wsl.sh` 下載到 WSL。

## 已知問題

立柱頂面只有 116 × 250 mm，RS007L 腳座是 190 × 220 mm，X 方向每邊會超出約 37 mm。
實際安裝前要確認底座頂板尺寸和螺絲孔位。
