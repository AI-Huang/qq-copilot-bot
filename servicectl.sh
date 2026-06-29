#!/usr/bin/env bash
# servicectl.sh — start / stop / restart / status for qq-copilot-bot and monitor
#
# Bot usage:
#   ./servicectl.sh {start|stop|restart|status|watch} [--prod|--dev|--env NAME]
#
# Monitor dashboard usage:
#   ./servicectl.sh monitor {start|stop|restart|status} [--port PORT] [--host HOST]

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths (relative to the script's own directory)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.bot.pid"
LOG_FILE="$SCRIPT_DIR/data/bot.log"
LOCK_FILE="$SCRIPT_DIR/.bot.lock"

MONITOR_PID_FILE="$SCRIPT_DIR/.monitor.pid"
MONITOR_LOG_FILE="$SCRIPT_DIR/data/monitor.log"
MONITOR_PORT="${MONITOR_PORT:-8787}"
MONITOR_HOST="${MONITOR_HOST:-127.0.0.1}"

# Ensure the log directories exist
mkdir -p "$(dirname "$LOG_FILE")"
mkdir -p "$(dirname "$MONITOR_LOG_FILE")"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_pid_running() {
    local pid="$1"
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

_read_pid() {
    [[ -f "$PID_FILE" ]] && cat "$PID_FILE" || echo ""
}

_pgid_of() {
    ps -o pgid= -p "$1" 2>/dev/null | tr -d ' '
}

_kill_group() {
    # Kill every process in the process group of the given PID.
    local pgid
    pgid=$(_pgid_of "$1")
    [[ -n "$pgid" ]] && kill -- "-$pgid" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
cmd_start() {
    local pid
    pid=$(_read_pid)
    if _pid_running "$pid"; then
        echo "[servicectl] Already running (PID $pid)."
        return 0
    fi

    # Forward any extra flags (--prod / --dev / --env NAME) to bot.py
    local extra_args=("$@")

    echo "[servicectl] Starting qq-copilot-bot (watch mode)..."
    cd "$SCRIPT_DIR"

    # Launch watchdog in its own session so all children share a process group.
    # setsid ensures kill -- -<pgid> on stop takes down uv + python too.
    setsid bash -c "
        while true; do
            uv run python bot.py ${extra_args[*]} >> \"$LOG_FILE\" 2>&1
            echo \"[servicectl] \$(date '+%Y-%m-%d %H:%M:%S') Bot exited (code \$?). Restarting in 5s...\" >> \"$LOG_FILE\"
            sleep 5
        done
    " >> "$LOG_FILE" 2>&1 &
    local new_pid=$!
    echo "$new_pid" > "$PID_FILE"

    # Give it a moment to confirm it didn't exit immediately
    sleep 2
    if _pid_running "$new_pid"; then
        echo "[servicectl] Started watchdog (PID $new_pid). Log: $LOG_FILE"
    else
        echo "[servicectl] Watchdog exited immediately — check $LOG_FILE" >&2
        rm -f "$PID_FILE"
        return 1
    fi
}

cmd_stop() {
    local pid
    pid=$(_read_pid)
    if ! _pid_running "$pid"; then
        echo "[servicectl] Not running."
        rm -f "$PID_FILE"
        return 0
    fi

    echo "[servicectl] Stopping (PID $pid, PGID $(_pgid_of "$pid"))..."
    _kill_group "$pid"

    # Wait up to 10 s for graceful shutdown
    local waited=0
    while _pid_running "$pid" && (( waited < 10 )); do
        sleep 1
        (( waited++ ))
    done

    if _pid_running "$pid"; then
        echo "[servicectl] Graceful shutdown timed out; force-killing group..."
        local pgid
        pgid=$(_pgid_of "$pid")
        [[ -n "$pgid" ]] && kill -9 -- "-$pgid" 2>/dev/null || true
    fi

    rm -f "$PID_FILE"
    echo "[servicectl] Stopped."
}

cmd_restart() {
    cmd_stop
    sleep 1
    cmd_start "$@"
}

cmd_watch() {
    local delay="${1:-5}"   # seconds between restarts (default 5)
    shift || true
    local extra_args=("$@")

    echo "[servicectl] Watch mode: bot will auto-restart on crash (delay=${delay}s). Ctrl+C to stop."
    while true; do
        cd "$SCRIPT_DIR"
        uv run python bot.py "${extra_args[@]}" >> "$LOG_FILE" 2>&1
        local exit_code=$?
        echo "[servicectl] $(date '+%Y-%m-%d %H:%M:%S') Bot exited (code $exit_code). Restarting in ${delay}s..."
        sleep "$delay"
    done
}

cmd_status() {
    local pid
    pid=$(_read_pid)
    if [[ -z "$pid" ]]; then
        echo "[servicectl] Status: stopped (no PID file)."
        return 1
    fi
    if _pid_running "$pid"; then
        echo "[servicectl] Status: running (PID $pid)."
        return 0
    else
        echo "[servicectl] Status: dead (stale PID $pid)."
        rm -f "$PID_FILE"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Monitor commands
# ---------------------------------------------------------------------------
monitor_start() {
    local pid host port
    pid=$(_monitor_read_pid)
    if _pid_running "$pid"; then
        echo "[monitor] Already running (PID $pid)."
        return 0
    fi

    # Parse --host / --port overrides from caller args
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --port) MONITOR_PORT="$2"; shift 2 ;;
            --host) MONITOR_HOST="$2"; shift 2 ;;
            *) shift ;;
        esac
    done

    echo "[monitor] Starting monitor dashboard on http://$MONITOR_HOST:$MONITOR_PORT ..."
    cd "$SCRIPT_DIR"

    setsid bash -c "
        while true; do
            uv run python scripts/monitor.py web --host \"$MONITOR_HOST\" --port \"$MONITOR_PORT\" >> \"$MONITOR_LOG_FILE\" 2>&1
            echo \"[monitor] \$(date '+%Y-%m-%d %H:%M:%S') Monitor exited (code \$?). Restarting in 5s...\" >> \"$MONITOR_LOG_FILE\"
            sleep 5
        done
    " >> "$MONITOR_LOG_FILE" 2>&1 &
    local new_pid=$!
    echo "$new_pid" > "$MONITOR_PID_FILE"

    sleep 2
    if _pid_running "$new_pid"; then
        echo "[monitor] Started (PID $new_pid). Log: $MONITOR_LOG_FILE"
    else
        echo "[monitor] Exited immediately — check $MONITOR_LOG_FILE" >&2
        rm -f "$MONITOR_PID_FILE"
        return 1
    fi
}

_monitor_read_pid() {
    [[ -f "$MONITOR_PID_FILE" ]] && cat "$MONITOR_PID_FILE" || echo ""
}

monitor_stop() {
    local pid
    pid=$(_monitor_read_pid)
    if ! _pid_running "$pid"; then
        echo "[monitor] Not running."
        rm -f "$MONITOR_PID_FILE"
        return 0
    fi

    echo "[monitor] Stopping (PID $pid)..."
    _kill_group "$pid"

    local waited=0
    while _pid_running "$pid" && (( waited < 10 )); do
        sleep 1
        (( waited++ ))
    done

    if _pid_running "$pid"; then
        local pgid
        pgid=$(_pgid_of "$pid")
        [[ -n "$pgid" ]] && kill -9 -- "-$pgid" 2>/dev/null || true
    fi

    rm -f "$MONITOR_PID_FILE"
    echo "[monitor] Stopped."
}

monitor_restart() {
    monitor_stop
    sleep 1
    monitor_start "$@"
}

monitor_status() {
    local pid
    pid=$(_monitor_read_pid)
    if [[ -z "$pid" ]]; then
        echo "[monitor] Status: stopped (no PID file)."
        return 1
    fi
    if _pid_running "$pid"; then
        echo "[monitor] Status: running (PID $pid) — http://$MONITOR_HOST:$MONITOR_PORT"
        return 0
    else
        echo "[monitor] Status: dead (stale PID $pid)."
        rm -f "$MONITOR_PID_FILE"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
COMMAND="${1:-}"
shift || true   # remaining args forwarded to bot.py / monitor where applicable

case "$COMMAND" in
    start)   cmd_start   "$@" ;;
    stop)    cmd_stop          ;;
    restart) cmd_restart "$@" ;;
    status)  cmd_status        ;;
    watch)   cmd_watch   "$@" ;;
    monitor)
        SUBCMD="${1:-}"; shift || true
        case "$SUBCMD" in
            start)   monitor_start   "$@" ;;
            stop)    monitor_stop          ;;
            restart) monitor_restart "$@" ;;
            status)  monitor_status        ;;
            *)
                echo "Usage: $0 monitor {start|stop|restart|status} [--port PORT] [--host HOST]" >&2
                exit 1
                ;;
        esac
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|watch} [--prod|--dev|--env NAME]" >&2
        echo "       $0 monitor {start|stop|restart|status} [--port PORT] [--host HOST]" >&2
        echo "       watch [DELAY_SECS] [--prod|--dev] — foreground watchdog loop" >&2
        exit 1
        ;;
esac
