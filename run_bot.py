"""Entry point — run from project root: python run_bot.py"""
import os
import sys

PID_FILE = ".tmp/bot.pid"

def _check_already_running():
    os.makedirs(".tmp", exist_ok=True)
    if os.path.exists(PID_FILE):
        with open(PID_FILE) as f:
            old_pid = f.read().strip()
        try:
            pid = int(old_pid)
            # Check if that process is still alive
            import psutil
            if psutil.pid_exists(pid):
                proc = psutil.Process(pid)
                if "python" in proc.name().lower():
                    print(f"Bot already running (PID {pid}). Exiting.")
                    sys.exit(1)
        except Exception:
            pass  # stale PID file — proceed
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

def _cleanup_pid():
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass

if __name__ == "__main__":
    import time
    print("Waiting 30s for any previous connection to close...")
    time.sleep(30)
    _check_already_running()
    try:
        from tools.telegram_webhook import main
        main()
    finally:
        _cleanup_pid()
