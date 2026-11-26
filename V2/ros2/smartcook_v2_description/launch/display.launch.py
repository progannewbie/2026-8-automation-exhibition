"""在 RViz 顯示 SmartCook V2 底座 + 兩支側裝 RS007L + 煎台，附吋動面板。

    ros2 launch smartcook_v2_description display.launch.py
    ros2 launch smartcook_v2_description display.launch.py mount_roll:=1.5708
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

# 最早「手臂裝在立柱頂端」版本的參數。現在改成側裝，這些參數不存在了；
# 但 mount_y / mount_z 名稱還在、意思不同，舊指令會把手臂裝到立柱裡、一直顯示干涉。
OLD_ARGS = ("mount_x", "mount_yaw")


def check_old_args(context):
    old = [a for a in OLD_ARGS if a in context.launch_configurations]
    if old:
        raise RuntimeError(
            f"{', '.join(old)} 是舊版（手臂裝在立柱頂端）的參數，現在手臂側裝在立柱兩側。\n"
            "直接用：ros2 launch smartcook_v2_description display.launch.py\n"
            "要調安裝位置改用 plate_x / mount_y / mount_z / mount_roll（見 V2/ros2/README.md）。")
    return []


def generate_launch_description():
    share = get_package_share_directory("smartcook_v2_description")
    xacro_file = os.path.join(share, "urdf", "smartcook_v2.urdf.xacro")
    rviz_file = os.path.join(share, "rviz", "display.rviz")

    # 預設值要和 urdf/smartcook_v2.urdf.xacro 的 xacro:arg 一致
    mount_args = {
        "plate_x": "0.058",
        "mount_y": "0.108",
        "mount_z": "1.109",
        "mount_roll": "0.0",
    }
    declares = [DeclareLaunchArgument(k, default_value=v) for k, v in mount_args.items()]

    xacro_cmd = ["xacro ", xacro_file]
    for k in mount_args:
        xacro_cmd += [f" {k}:=", LaunchConfiguration(k)]
    robot_description = ParameterValue(Command(xacro_cmd), value_type=str)

    return LaunchDescription(declares + [
        OpaqueFunction(function=check_old_args),
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            parameters=[{"robot_description": robot_description}],
        ),
        # 吋動面板：軸 / 基座 / 工具 / 世界座標吋動，並調整煎台位置（取代 joint_state_publisher_gui）
        Node(
            package="smartcook_v2_description",
            executable="jog_panel.py",
            parameters=[{
                "robot_description": robot_description,
                # colcon --symlink-install 時這是指回 repo 的連結，儲存會直接寫回 repo 的 config/scene.yaml
                "scene_file": os.path.join(share, "config", "scene.yaml"),
            }],
        ),
        Node(
            package="rviz2",
            executable="rviz2",
            arguments=["-d", rviz_file],
        ),
    ])
