cmake_minimum_required(VERSION 3.8)
project(smartcook_v2_description)

find_package(ament_cmake REQUIRED)

install(DIRECTORY meshes urdf launch rviz config
  DESTINATION share/${PROJECT_NAME})

install(PROGRAMS scripts/jog_panel.py
  DESTINATION lib/${PROJECT_NAME})

ament_package()
