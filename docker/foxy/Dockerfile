FROM ros:foxy-ros-base

SHELL ["/bin/bash", "-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      cmake \
      git \
      libacl1-dev \
      libssl-dev \
      libyaml-cpp-dev \
      python3-colcon-common-extensions \
      ros-foxy-rmw-cyclonedds-cpp \
      ros-foxy-rosidl-generator-dds-idl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/unitree-src \
    && git clone --depth 1 --branch 0.10.2 \
         https://github.com/eclipse-cyclonedds/cyclonedds.git \
         /opt/unitree-src/cyclonedds \
    && true

WORKDIR /workspace
