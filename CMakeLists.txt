cmake_minimum_required(VERSION 3.5)
project(g1_motion_player VERSION 1.0.0)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Unitree SDK (submodule)
add_subdirectory(thirdparty/unitree_sdk2)

# csv_replay: upper-body keyframe replay
add_executable(csv_replay src/csv_replay.cpp)
target_link_libraries(csv_replay unitree_sdk2)

# test_connection: minimal connection test
add_executable(test_connection src/test_connection.cpp)
target_link_libraries(test_connection unitree_sdk2)
