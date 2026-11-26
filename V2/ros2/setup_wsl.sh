#!/usr/bin/env bash
# 在 WSL (Ubuntu 24.04 + ROS 2 Jazzy) 建立 SmartCook V2 的 ROS 2 工作區
#
#   bash /mnt/d/smartcook/V2/ros2/setup_wsl.sh
#
# 1. 下載 Kawasaki 官方 khi_rs_description（RS007L 模型，ROS 1 套件）
#    模型檔是 KHI CAD 授權，只放在 WSL，不放進 smartcook repo
# 2. 補上 ROS 2 用的 package.xml / CMakeLists.txt
# 3. 把 smartcook_v2_description、smartcook_rviz_plugins 連到 Windows 上的 repo，colcon build
set -euo pipefail

WS=~/smartcook_ws
REPO_PKG=/mnt/d/smartcook/V2/ros2/smartcook_v2_description
KHI=$WS/third_party/khi_robot

set +u; source /opt/ros/jazzy/setup.bash; set -u
mkdir -p "$WS/src" "$WS/third_party"
touch "$WS/third_party/COLCON_IGNORE"   # 原始 ROS 1 套件不要被 colcon 掃到

# 1. Kawasaki 官方模型
if [ ! -d "$KHI/khi_rs_description" ]; then
  git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/Kawasaki-Robotics/khi_robot.git "$KHI"
  git -C "$KHI" sparse-checkout set khi_rs_description
fi

# 2. ROS 2 版的套件設定（只需要 urdf 和 meshes）
KHI_PKG=$WS/src/khi_rs_description
mkdir -p "$KHI_PKG"
ln -sfn "$KHI/khi_rs_description/meshes" "$KHI_PKG/meshes"
# urdf 用複製的：拿掉巨集裡的 White / Black 材質定義（只保留引用），
# 否則同一個 URDF 放兩支 RS007L 時材質會重複定義、解析失敗。
# 這兩個顏色改由 smartcook_v2.urdf.xacro 定義一次。
rm -rf "$KHI_PKG/urdf"
cp -r "$KHI/khi_rs_description/urdf" "$KHI_PKG/urdf"
perl -0pi -e 's{\s*<material name="(White|Black)">\s*<color [^>]*/>\s*</material>}{}g' "$KHI_PKG"/urdf/*_macro.xacro
cat > "$KHI_PKG/package.xml" <<'EOF'
<?xml version="1.0"?>
<package format="3">
  <name>khi_rs_description</name>
  <version>1.4.0</version>
  <description>Kawasaki RS series description (ROS 2 wrapper of khi_robot/khi_rs_description)</description>
  <maintainer email="noreply@example.com">local</maintainer>
  <license>BSD</license>
  <buildtool_depend>ament_cmake</buildtool_depend>
  <export><build_type>ament_cmake</build_type></export>
</package>
EOF
cat > "$KHI_PKG/CMakeLists.txt" <<'EOF'
cmake_minimum_required(VERSION 3.8)
project(khi_rs_description)
find_package(ament_cmake REQUIRED)
install(DIRECTORY urdf/ DESTINATION share/${PROJECT_NAME}/urdf)
install(DIRECTORY meshes/ DESTINATION share/${PROJECT_NAME}/meshes)
ament_package()
EOF

# 3. SmartCook V2 套件（直接連到 repo，改檔案後重新 build 即可）
ln -sfn "$REPO_PKG" "$WS/src/smartcook_v2_description"
ln -sfn "$(dirname "$REPO_PKG")/smartcook_rviz_plugins" "$WS/src/smartcook_rviz_plugins"   # RViz 右鍵平移視角

cd "$WS"
colcon build --symlink-install

echo
echo "完成。開啟模擬："
echo "  source $WS/install/setup.bash"
echo "  ros2 launch smartcook_v2_description display.launch.py"
