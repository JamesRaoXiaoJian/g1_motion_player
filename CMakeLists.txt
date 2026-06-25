cmake_minimum_required(VERSION 3.5)
project(g1_motion_player VERSION 1.0.0)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Unitree SDK bundles CycloneDDS libs as .so files, but SONAME requires .so.0.
# Create missing SONAME symlinks so runtime linker can resolve dependencies.
set(UNITREE_DDS_LIB_DIR "")
if(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|amd64")
	set(UNITREE_DDS_LIB_DIR "${CMAKE_SOURCE_DIR}/thirdparty/unitree_sdk2/thirdparty/lib/x86_64")
elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64")
	set(UNITREE_DDS_LIB_DIR "${CMAKE_SOURCE_DIR}/thirdparty/unitree_sdk2/thirdparty/lib/aarch64")
endif()

if(UNITREE_DDS_LIB_DIR)
	foreach(lib_name IN ITEMS ddsc ddscxx)
		set(lib_so "${UNITREE_DDS_LIB_DIR}/lib${lib_name}.so")
		set(lib_soname "${UNITREE_DDS_LIB_DIR}/lib${lib_name}.so.0")
		if(EXISTS "${lib_so}" AND NOT EXISTS "${lib_soname}")
			execute_process(
				COMMAND "${CMAKE_COMMAND}" -E create_symlink "${lib_so}" "${lib_soname}"
				RESULT_VARIABLE symlink_result
			)
			if(NOT symlink_result EQUAL 0)
				message(WARNING "Failed to create symlink: ${lib_soname} -> ${lib_so}")
			endif()
		endif()
	endforeach()
endif()

# Unitree SDK (submodule)
add_subdirectory(thirdparty/unitree_sdk2)

# csv_replay: upper-body keyframe replay
add_executable(csv_replay src/csv_replay.cpp)
target_link_libraries(csv_replay unitree_sdk2)

# test_connection: minimal connection test
add_executable(test_connection src/test_connection.cpp)
target_link_libraries(test_connection unitree_sdk2)
