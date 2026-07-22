#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="g1-motion-player-foxy:0.10.2"

docker build \
  -t "${IMAGE_NAME}" \
  -f "${PROJECT_DIR}/docker/foxy/Dockerfile" \
  "${PROJECT_DIR}"

docker run --rm \
  -v "${PROJECT_DIR}:/workspace" \
  --entrypoint /bin/rm \
  "${IMAGE_NAME}" \
  -rf /workspace/.foxy

docker run --rm \
  --network host \
  --entrypoint /bin/bash \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -v "${PROJECT_DIR}:/workspace" \
  -w /workspace \
  "${IMAGE_NAME}" \
  -lc '
    set -eo pipefail
    colcon --log-base /workspace/.foxy/log build \
      --base-paths /opt/unitree-src/cyclonedds \
      --packages-select cyclonedds \
      --build-base /workspace/.foxy/build \
      --install-base /workspace/.foxy/install \
      --cmake-clean-cache \
      --cmake-args -DCMAKE_BUILD_TYPE=Release -DPython3_EXECUTABLE=/usr/bin/python3

    source /opt/ros/foxy/setup.bash
    source /workspace/.foxy/install/setup.bash
    colcon --log-base /workspace/.foxy/log build \
      --base-paths \
        /workspace/thirdparty/unitree_ros2/cyclonedds_ws/src/unitree \
        /workspace/thirdparty/unitree_ros2/example/src \
        /workspace/src/ros2 \
      --build-base /workspace/.foxy/build \
      --install-base /workspace/.foxy/install \
      --cmake-clean-cache \
      --cmake-args -DCMAKE_BUILD_TYPE=Release -DPython3_EXECUTABLE=/usr/bin/python3
  '

echo "Foxy workspace built: ${PROJECT_DIR}/.foxy/install"
