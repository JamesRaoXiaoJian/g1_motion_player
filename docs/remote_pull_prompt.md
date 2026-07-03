# 远端 PC2 拉取仓库与部署提示词

下面这段可以直接发给远端执行人员或另一个代码 agent，让它在宇树 G1 PC2 本机拉取最新主分支并完成部署验证。

```text
你现在在宇树 G1 的 PC2 本机上操作 g1_motion_player 仓库。目标是拉取远端 main 最新代码并完成本机部署验证。

要求：
1. 不要执行 git reset --hard。
2. 不要删除 assets/uploads/、本地录制数据或任何未确认文件。
3. 先检查工作区，如果有未提交修改，停止并汇报，不要覆盖。
4. 当前主分支只应暴露 POST /api/replay，不要恢复旧的 /api/motions 或 JSON replay。
5. 真实执行机器人动作前必须先 dry_run=true 验证，确认周围安全后才允许 dry_run=false。

请按顺序执行：

cd /home/unitree/g1_motion_player
git status --short --branch

# 如果上一步显示除未跟踪运行日志以外的修改，请停止并汇报。

git fetch origin
git switch main
git pull --ff-only origin main
git submodule update --init --recursive

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .

cmake -S . -B build
cmake --build build -j"$(nproc)" --target csv_replay
test -x build/csv_replay && echo "csv_replay ok"

python -m compileall -q api tests

# 检查运行时 API 路由，应只输出 POST /api/replay
python - <<'PY'
from api.main import create_app
for route in create_app().routes:
    print(route.path, sorted(route.methods))
PY

# 启动 API，若已有服务在运行，先汇报，不要强杀未知进程
python -m uvicorn api.main:app --host 127.0.0.1 --port 8001

# 另开终端 dry-run 验证
curl -X POST http://127.0.0.1:8001/api/replay \
  -F "file=@assets/wave.csv" \
  -F "save_as=pc2_pull_check" \
  -F "fps=50" \
  -F "dry_run=true"

仓库默认机器人通信网卡是 eth0；API 不接收 net 参数。如果 PC2 的机器人通信网卡不是 eth0，先修改 api/main.py 的 DEFAULT_ROBOT_NET 和 C++ 工具默认网卡，重新编译后再启动 API。
完成后汇报：当前 commit、git status、csv_replay 编译结果、API 路由检查结果、dry-run curl 返回。
```

## 纯命令版

如果确认 PC2 工作区干净，可以直接使用：

```bash
cd /home/unitree/g1_motion_player
git status --short --branch
git fetch origin
git switch main
git pull --ff-only origin main
git submodule update --init --recursive
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
cmake -S . -B build
cmake --build build -j"$(nproc)" --target csv_replay
python -m compileall -q api tests
python - <<'PY'
from api.main import create_app
print([(route.path, sorted(route.methods)) for route in create_app().routes])
PY
```
