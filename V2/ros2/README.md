# V2 ROS 2 模擬：底座 + 兩支 RS007L

在 WSL（Ubuntu 24.04 + ROS 2 Jazzy）用 RViz 顯示機器人底座，立柱頂端兩側各側裝一支 Kawasaki RS007L，加上煎台。
用吋動面板像教導器一樣操作：軸、基座、工具、世界四種座標，煎台位置可以隨時調整並存檔。

## 第一次安裝

在 Windows 終端機執行（會下載 Kawasaki 官方 RS007L 模型到 WSL 的 `~/smartcook_ws`，並編譯）：

```bash
wsl -d Ubuntu -- bash /mnt/d/smartcook/V2/ros2/setup_wsl.sh
```

## 開啟模擬

```bash
wsl -d Ubuntu -- bash -c "source ~/smartcook_ws/install/setup.bash && ros2 launch smartcook_v2_description display.launch.py"
```

會開兩個視窗：RViz（3D 畫面）和「SmartCook V2 吋動面板」。

## 吋動面板

1. 選手臂：右臂 (+X) / 左臂 (-X)
2. 選座標：

   | 模式 | 6 個按鈕 | 方向依據 |
   |---|---|---|
   | 軸 | JT1～JT6 | 各軸單獨轉 |
   | 基座 | X Y Z Rx Ry Rz | 所選手臂自己的 base_link（側裝，所以 Z 是水平朝外） |
   | 工具 | X Y Z Rx Ry Rz | TCP 自己的軸 |
   | 世界 | X Y Z Rx Ry Rz | 地面座標（Z 朝上，X/Y 同 CAD） |

   直線移動和旋轉都以 TCP 為中心，姿態不變時只平移。
3. 按住 − / + 就會持續動，放開就停。速度滑桿 100% = 直線 100 mm/s、旋轉 30°/s、軸 30°/s。
4. 面板會顯示：
   - 各軸角度
   - TCP 位置分別在「基座」「世界」「煎台」三種座標下的 X Y Z（mm）和 O A T（deg）
     - O A T 和 Kawasaki 教導器一樣是 ZYZ 尤拉角
     - 煎台座標的原點是煎台頂面中心，可以直接看 TCP 離煎台多遠
5. 碰到軸極限會停住並顯示是哪一軸；接近奇異點（例如手臂伸直）時會提醒，TCP 可能跟不上指令。

「回原點」把兩支手臂所有軸歸零（手臂水平往外伸）。

> 這是運動學模擬：沒有碰撞檢查，手臂可以穿過底座或煎台。

### 工具座標（TCP）

平鏟還沒設計，TCP 預設在 link6 法蘭面中心。面板上可以改 TCP 相對法蘭的 X / Y / Z（mm），工具模式和位置顯示會跟著變。

## 煎台

煎台位置還沒定，先放在立柱前方（世界座標 X 0、Y -600、頂面高 850 mm，600 × 400 × 60 mm）。

- 在面板的「煎台」欄位改位置、旋轉、長寬厚，RViz 會立刻更新。
- 按「儲存設定」會寫回 [smartcook_v2_description/config/scene.yaml](smartcook_v2_description/config/scene.yaml)（連同 TCP 偏移），下次開啟就用新的值。記得把這個檔 commit。
- 也可以直接改這個 yaml 再重新開啟模擬。

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

- `smartcook_v2_description/scripts/jog_panel.py`：吋動面板，同時發佈 `/joint_states`、煎台標記 `/smartcook_scene`、TF（`griddle`、`right_tcp`、`left_tcp`）
- `smartcook_v2_description/config/scene.yaml`：煎台位置、尺寸和 TCP 偏移
- `smartcook_v2_description/meshes/robot_base.stl`：底座模型，複製自 `V2/圖檔/robot base.stl`（和 `robot_base.step` 尺寸相同，單位 mm）。底座改版後要重新匯出 STL 並覆蓋這個檔。
- RS007L 模型不在這個 repo：它是 Kawasaki 的 CAD 授權，由 `setup_wsl.sh` 下載到 WSL。
  setup 會拿掉 Kawasaki 巨集裡的 White / Black 材質定義（改由我們的 xacro 定義一次），否則兩支手臂會重複定義、URDF 解析失敗。
