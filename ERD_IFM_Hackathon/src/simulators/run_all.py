"""
Run all three device simulators simultaneously.

Usage:
    python src/simulators/run_all.py

Each simulator runs in its own daemon thread. Press Ctrl+C to stop.
"""
import sys
import os
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.simulators.boiler import run as run_boiler
from src.simulators.pasteurizer import run as run_pasteurizer
from src.simulators.dryer import run as run_dryer

GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def main():
    print(f"{GREEN}{'='*60}{RESET}")
    print(f"{GREEN}  IFM Device Simulator — All Devices{RESET}")
    print(f"{GREEN}{'='*60}{RESET}")
    print(f"{YELLOW}  Boiler      → boiler-line-1   (every 5s){RESET}")
    print(f"{YELLOW}  Pasteurizer → past-01          (every 5s){RESET}")
    print(f"{YELLOW}  Dryer       → dryer-01         (every 5s){RESET}")
    print(f"{GREEN}{'='*60}{RESET}")
    print("  Press Ctrl+C to stop all simulators\n")

    threads = [
        threading.Thread(target=run_boiler, name="Boiler", daemon=True),
        threading.Thread(target=run_pasteurizer, name="Pasteurizer", daemon=True),
        threading.Thread(target=run_dryer, name="Dryer", daemon=True),
    ]

    for t in threads:
        t.start()

    try:
        # Keep main thread alive while daemon threads run
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print(f"\n{YELLOW}[run_all] Stopping all simulators...{RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()
