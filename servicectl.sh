#!/usr/bin/env bash
# servicectl.sh — start / stop / restart / status for qq-copilot-bot
# Usage: ./servicectl.sh {start|stop|restart|status} [--prod|--dev|--env NAME]

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths (relative to the script's own directory)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.bot.pid"
LOG_FILE="$SCRIPT_DIR/data/bot.log"
LOCK_FILE="$SCRIPT_DIR/.bot.lock"

# Ensure the log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

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

    # Launch watchdog loop detached; it restarts the bot on crash automatically.
    nohup bash -c "
        while true; do
            uv run python bot.py ${extra_args[*]} >> \"$LOG_FILE\" 2>&1
            echo \"[servicectl] \$(date '+%Y-%m-%d %H:%M:%S') Bot exited (code \$?). Restarting in 5s...\" >> \"$LOG_FILE\"
            sleep 5
        done
    " &
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

    echo "[servicectl] Stopping (PID $pid)..."
    kill "$pid"

    # Wait up to 10 s for graceful shutdown
    local waited=0
    while _pid_running "$pid" && (( waited < 10 )); do
        sleep 1
        (( waited++ ))
    done

    if _pid_running "$pid"; then
        echo "[servicectl] Graceful shutdown timed out; sending SIGKILL..."
        kill -9 "$pid" 2>/dev/null || true
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
# Dispatch
# ---------------------------------------------------------------------------
COMMAND="${1:-}"
shift || true   # remaining args forwarded to bot.py where applicable

case "$COMMAND" in
    start)   cmd_start   "$@" ;;
    stop)    cmd_stop          ;;
    restart) cmd_restart "$@" ;;
    status)  cmd_status        ;;
    watch)   cmd_watch   "$@" ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|watch} [--prod|--dev|--env NAME]" >&2
        echo "       watch [DELAY_SECS] [--prod|--dev] — foreground watchdog loop" >&2
        exit 1
        ;;
esac
