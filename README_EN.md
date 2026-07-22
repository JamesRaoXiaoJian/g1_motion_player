# G1 Motion Player

<p align="center">
  <a href="README.md">中文</a> · <a href="README_EN.md">English</a>
</p>

A Unitree G1 motion replay tool for sending CSV joint motions to the G1 upper-body `rt/arm_sdk` control path. The repository includes a C++ runtime replay program, a local FastAPI HTTP interface, CSV validation, connection utilities, tests, and sample motions.

The current `main` branch intentionally keeps only the CSV execution path:

- C++ execution layer: `csv_replay` reads CSV frames and publishes commands through Unitree SDK DDS.
- HTTP layer: FastAPI exposes only `POST /api/replay`, validates uploaded CSV data, saves it, and optionally invokes `csv_replay`.
- Sample motions: `assets/wave.csv` and `assets/zuoyi.csv`.
- ROS2 Docker runtime: pinned Foxy and CycloneDDS 0.10.2 for `/lowstate` and `/arm_sdk` communication.

Older JSON replay and motion CRUD versions are archived in the remote branch `api-json-replay-archive`.

## Highlights

- CSV validation, saving, and execution with `dry_run=true` by default to prevent accidental robot motion.
- C++ `csv_replay` sends commands directly to the Unitree G1 `rt/arm_sdk` topic.
- FastAPI exposes only `POST /api/replay`; `/docs`, `/redoc`, and `/openapi.json` are disabled.
- Nearest-window entry/exit frame selection and velocity clamping reduce sudden pose jumps.
- Includes `state_recorder`, `test_connection`, API tests, and CSV validation tests.

## Repository Layout

```text
g1_motion_player/
├── api/
│   ├── main.py                # FastAPI: POST /api/replay
│   └── csv_motion.py          # CSV validation and metadata parsing
├── assets/
│   ├── wave.csv
│   └── zuoyi.csv
├── src/
│   ├── csv_replay.cpp         # Production replay program
│   ├── csv_replay_debug.cpp   # Debug replay path
│   ├── g1_mode_switch.cpp
│   ├── state_recorder.cpp
│   └── test_connection.cpp
├── tests/
├── docker/foxy/                # ROS2 Foxy utilities and control scripts
├── docs/ros2_docker.md         # Docker workflow guide
├── build_foxy_docker.sh
├── run_foxy_docker.sh
└── thirdparty/
    ├── unitree_sdk2/           # SDK2 git submodule
    └── unitree_ros2/           # vendored Unitree ROS2 source
```

## Recommended ROS2 Docker workflow

New development should use the pinned ROS2 Foxy Docker environment. The host does not need ROS2 Foxy installed.

```bash
./build_foxy_docker.sh
./run_foxy_docker.sh
```

For a network interface other than `wlo1`:

```bash
UNITREE_NET_IFACE=wlan0 ./run_foxy_docker.sh
```

Inside the container:

```bash
ros2 topic echo /lowstate unitree_hg/msg/LowState
python3 docker/foxy/measure_lowstate_rate.py --duration 10
ros2 run g1_motion_player_ros2 csv_replay_ros2 assets/wave.csv
```

See [docs/ros2_docker.md](docs/ros2_docker.md) for the full workflow and safety requirements.

## Requirements

Recommended runtime environment:

- Ubuntu 20.04 / 22.04
- x86_64 or aarch64
- GCC 9.4+
- CMake 3.5+
- Python 3.11+
- Unitree G1 and the runtime machine on the same wired network

Install basic system dependencies:

```bash
sudo apt-get update
sudo apt-get install -y \
  git cmake g++ build-essential pkg-config \
  python3 python3-venv python3-pip
```

Initialize submodules:

```bash
git submodule update --init --recursive
```

Create the Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

Recommended `uv` environment setup (Linux/macOS):

```bash
# Linux:
curl -LsSf https://astral.sh/uv/install.sh | sh

# macOS:
brew install uv
```

After installation, create the virtual environment and install dependencies with:

```bash
uv venv .venv
source .venv/bin/activate
uv pip install --upgrade pip
uv pip install -e ".[dev]"
```

Build C++ binaries:

```bash
cmake -S . -B build
cmake --build build -j"$(nproc)"
```

Expected binaries:

```text
build/csv_replay
build/state_recorder
build/test_connection
```

## Run on G1 PC2

See [docs/g1_robot_deployment.md](docs/g1_robot_deployment.md) for the full deployment flow.

Check the network interface first:

```bash
ip link
```

The repository defaults to `eth0` for robot communication. If your PC2 uses `eth0`, run:

```bash
./build/csv_replay assets/wave.csv 50 eth0
```

Command format:

```bash
./build/csv_replay <csv-file> [fps] [network-interface]
```

Common examples:

```bash
./build/csv_replay assets/wave.csv
./build/csv_replay assets/wave.csv 50 eth0
./build/csv_replay assets/zuoyi.csv 50 eth0
```

## Start the API

For local testing, bind only to `127.0.0.1`:

```bash
source .venv/bin/activate
python -m uvicorn api.main:app --host 127.0.0.1 --port 8001
```

To expose the API inside a trusted LAN:

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8001
```

The current `main` branch does not include built-in authentication. If the API is exposed beyond localhost, add authentication or firewall restrictions outside the app.

## POST /api/replay

The API accepts CSV data only. It does not accept motion names or JSON motion frames.

By default, `dry_run=true`, which validates and saves the CSV without moving the robot. Real execution requires `dry_run=false` and a compiled `build/csv_replay` binary.

### Multipart Upload

```bash
curl -X POST http://127.0.0.1:8001/api/replay \
  -F "file=@assets/wave.csv" \
  -F "save_as=wave_upload" \
  -F "fps=50" \
  -F "dry_run=true"
```

Real execution:

```bash
curl -X POST http://127.0.0.1:8001/api/replay \
  -F "file=@assets/wave.csv" \
  -F "save_as=wave_run" \
  -F "fps=50" \
  -F "dry_run=false"
```

## CSV Format

The replay CSV must use the G1 arm motion format expected by `api/csv_motion.py` and `src/csv_replay.cpp`. Use the included `assets/wave.csv` and `assets/zuoyi.csv` as references. Invalid CSV files are rejected and are not kept as final uploaded files.

## Tests

Python tests:

```bash
source .venv/bin/activate
python -m pytest
```

C++ build check:

```bash
cmake -S . -B build
cmake --build build -j"$(nproc)"
test -x build/csv_replay
test -x build/state_recorder
test -x build/test_connection
```

If you hit:

```text
Package 'g1-motion-player-api' requires a different Python
```

it usually means your virtualenv is using a Python version below the project minimum (`>= 3.11`). Recreate your environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

Create the venv with Python 3.11+:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

## Safety Notes

- Keep `dry_run=true` until the CSV has been validated and the robot environment is ready.
- Run the API on `127.0.0.1` unless the network is trusted and access-controlled.
- Confirm the G1 communication network interface before real execution.
- Use the provided transition strategy and velocity clamping to reduce sudden posture jumps.
