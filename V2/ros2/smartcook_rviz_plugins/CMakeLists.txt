cmake_minimum_required(VERSION 3.8)
project(smartcook_rviz_plugins)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()

find_package(ament_cmake REQUIRED)
find_package(pluginlib REQUIRED)
find_package(rviz_common REQUIRED)
find_package(rviz_default_plugins REQUIRED)
find_package(Qt5 REQUIRED COMPONENTS Widgets)

add_library(${PROJECT_NAME} SHARED
  src/right_pan_orbit_view_controller.cpp)
target_link_libraries(${PROJECT_NAME}
  pluginlib::pluginlib
  rviz_common::rviz_common
  rviz_default_plugins::rviz_default_plugins
  Qt5::Widgets)

pluginlib_export_plugin_description_file(rviz_common plugins_description.xml)

install(TARGETS ${PROJECT_NAME}
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION bin)

ament_package()
