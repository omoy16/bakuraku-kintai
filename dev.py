"""Run local development commands from any working directory."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="爆楽勤怠 ローカル開発コマンド")
    parser.add_argument("command", choices=("init-db", "api", "test", "frontend", "build"))
    args = parser.parse_args()

    if args.command == "init-db":
        sys.path.insert(0, str(ROOT / "backend"))
        from app.database import init_db

        print(f"SQLite ready: {init_db()}")
        return 0

    if args.command in ("frontend", "build"):
        npm = shutil.which("npm")
        if npm is None:
            parser.error("npm が見つかりません。Node.js と npm をインストールしてください。")
        command = [npm, "run", "dev" if args.command == "frontend" else "build"]
        cwd = ROOT / "frontend"
    elif args.command == "api":
        command = [sys.executable, "-m", "uvicorn", "app.main:app", "--reload",
                   "--host", "127.0.0.1", "--port", "8000"]
        cwd = ROOT / "backend"
    else:
        command = [sys.executable, "-m", "pytest"]
        cwd = ROOT

    try:
        return subprocess.call(command, cwd=cwd)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
