#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="g1-motion-player-foxy:0.10.2"
NET_IFACE="${UNITREE_NET_IFACE:-wlo1}"

if ! docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1; then
  echo "Image ${IMAGE_NAME} not found. Run ./build_foxy_docker.sh first." >&2
  exit 1
fi

docker run --rm -it \
  --network host \
  --user "$(id -u):$(id -g)" \
  -v "${PROJECT_DIR}:/workspace" \
  -w /workspace \
  -e HOME=/tmp \
  -e "UNITREE_NET_IFACE=${NET_IFACE}" \
  "${IMAGE_NAME}" \
  bash -lc '
    source /opt/ros/foxy/setup.bash
    source /workspace/.foxy/install/setup.bash
    export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
    export ROS_DOMAIN_ID=0
    export ROS_LOCALHOST_ONLY=0
    export CYCLONEDDS_URI="<CycloneDDS><Domain Id=\"any\"><General><Interfaces><NetworkInterface name=\"${UNITREE_NET_IFACE}\"/></Interfaces><AllowMulticast>true</AllowMulticast></General></Domain></CycloneDDS>"
    exec bash
  '

