cmake_minimum_required(VERSION 3.5)
project(g1_motion_player_ros2)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(unitree_hg REQUIRED)

add_executable(csv_replay_ros2 csv_replay_ros2.cpp)
target_compile_features(csv_replay_ros2 PRIVATE cxx_std_17)
target_include_directories(csv_replay_ros2 PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/..)
ament_target_dependencies(csv_replay_ros2 rclcpp unitree_hg)

install(TARGETS csv_replay_ros2 DESTINATION lib/${PROJECT_NAME})
ament_package()
