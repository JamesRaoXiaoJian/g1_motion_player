cmake_minimum_required(VERSION 3.5)
project(g1_motion_player VERSION 1.0.0)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Unitree SDK bundles CycloneDDS libs as .so files, but SONAME requires .so.0.
# Create symlinks in BUILD dir (not in submodule) to avoid dirtying the submodule.
set(UNITREE_DDS_LIB_DIR "")
if(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|amd64")
	set(UNITREE_DDS_LIB_DIR "${CMAKE_SOURCE_DIR}/thirdparty/unitree_sdk2/thirdparty/lib/x86_64")
elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64")
	set(UNITREE_DDS_LIB_DIR "${CMAKE_SOURCE_DIR}/thirdparty/unitree_sdk2/thirdparty/lib/aarch64")
endif()

if(UNITREE_DDS_LIB_DIR)
	foreach(lib_name IN ITEMS ddsc ddscxx)
		set(lib_so "${UNITREE_DDS_LIB_DIR}/lib${lib_name}.so")
		set(lib_soname "${CMAKE_BINARY_DIR}/lib${lib_name}.so.0")
		# Create relative symlink in build dir pointing to source .so
		if(EXISTS "${lib_so}" AND NOT EXISTS "${lib_soname}")
			file(CREATE_LINK "${lib_so}" "${lib_soname}" SYMBOLIC)
		endif()
	endforeach()
	# Tell linker to look in build dir for .so.0 at runtime
	link_directories("${CMAKE_BINARY_DIR}")
endif()

# Unitree SDK (submodule)
add_subdirectory(thirdparty/unitree_sdk2)

# csv_replay: upper-body keyframe replay
add_executable(csv_replay src/csv_replay.cpp)
target_link_libraries(csv_replay unitree_sdk2)

# test_connection: minimal connection test
add_executable(test_connection src/test_connection.cpp)
target_link_libraries(test_connection unitree_sdk2)

# state_recorder: record robot joint states to CSV
add_executable(state_recorder src/state_recorder.cpp)
target_link_libraries(state_recorder unitree_sdk2)

# csv_replay_debug: full-body CSV replay via debug mode (rt/user_lowcmd)
add_executable(csv_replay_debug src/csv_replay_debug.cpp)
target_link_libraries(csv_replay_debug unitree_sdk2)

# g1_mode_switch: FSM mode switching utility
add_executable(g1_mode_switch src/g1_mode_switch.cpp)
target_link_libraries(g1_mode_switch unitree_sdk2)
