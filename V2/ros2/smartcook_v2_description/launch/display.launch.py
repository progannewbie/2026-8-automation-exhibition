"""在 RViz 顯示 SmartCook V2 底座 + 兩支側裝 RS007L，附關節滑桿。

    ros2 launch smartcook_v2_description display.launch.py
    ros2 launch smartcook_v2_description display.launch.py mount_roll:=1.5708
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


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
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            parameters=[{"robot_description": robot_description}],
        ),
        Node(
            package="joint_state_publisher_gui",
            executable="joint_state_publisher_gui",
        ),
        Node(
            package="rviz2",
            executable="rviz2",
            arguments=["-d", rviz_file],
        ),
    ])
