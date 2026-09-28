#!/usr/bin/env bash
set -eo pipefail

WORKSPACE="${HOME}/ros2_ws"
MOCK_ENABLED=false

PIDS=()
START_PERCEPTION=false
START_BEHAVIOR=false
START_EXECUTOR=false

show_usage() {
    cat <<EOF
用法：
  $0 perception [behavior] [executor] [--mock=true|false]
  $0 all [--mock=true|false]

示例：
  $0 executor
  $0 perception
  $0 perception behavior --mock=false
  $0 behavior executor
  $0 all --mock=true
EOF
}

cleanup() {
    trap - EXIT INT TERM

    if ((${#PIDS[@]} > 0)); then
        echo
        echo "正在停止 MarsDog 进程……"
        kill "${PIDS[@]}" 2>/dev/null || true
        wait "${PIDS[@]}" 2>/dev/null || true
    fi
}

start_perception() {
    echo "启动 perception，mock_enabled=${MOCK_ENABLED}"
    ros2 launch marsdog_perception perception.launch.py \
        mock_enabled:="${MOCK_ENABLED}" &
    PIDS+=("$!")
}

start_behavior() {
    echo "启动 behavior"
    ros2 launch marsdog_behavior behavior_tree.launch.py &
    PIDS+=("$!")
}

start_executor() {
    echo "启动 executor"
    ros2 run marsdog_action_executor action_executor_node &
    PIDS+=("$!")
}

if (($# == 0)); then
    show_usage
    exit 1
fi

for arg in "$@"; do
    case "$arg" in
        perception)
            START_PERCEPTION=true
            ;;
        behavior)
            START_BEHAVIOR=true
            ;;
        executor)
            START_EXECUTOR=true
            ;;
        all)
            START_PERCEPTION=true
            START_BEHAVIOR=true
            START_EXECUTOR=true
            ;;
        --mock=true)
            MOCK_ENABLED=true
            ;;
        --mock=false)
            MOCK_ENABLED=false
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            echo "未知参数：$arg" >&2
            show_usage
            exit 1
            ;;
    esac
done

if [[ "$START_PERCEPTION" == false &&
      "$START_BEHAVIOR" == false &&
      "$START_EXECUTOR" == false ]]; then
    echo "没有指定需要启动的模块。" >&2
    exit 1
fi

if [[ ! -d "$WORKSPACE" ]]; then
    echo "工作空间不存在：$WORKSPACE" >&2
    exit 1
fi

if [[ ! -f "${WORKSPACE}/install/setup.bash" ]]; then
    echo "未找到：${WORKSPACE}/install/setup.bash" >&2
    echo "请先执行：" >&2
    echo "  cd ${WORKSPACE}" >&2
    echo "  colcon build --symlink-install" >&2
    exit 1
fi

cd "$WORKSPACE"

# 避免 setup.bash 因未定义变量触发 nounset 错误
set +u
source "${WORKSPACE}/install/setup.bash"
set -u

if ! command -v ros2 >/dev/null 2>&1; then
    echo "加载环境后仍未找到 ros2 命令。" >&2
    exit 1
fi

trap cleanup EXIT INT TERM

[[ "$START_PERCEPTION" == true ]] && start_perception
[[ "$START_BEHAVIOR" == true ]] && start_behavior
[[ "$START_EXECUTOR" == true ]] && start_executor

echo
echo "MarsDog 已启动，按 Ctrl+C 停止。"

wait