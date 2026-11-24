"""PyInstaller entry point for openwarframe-cli.exe (console CLI)."""

from openwarframe.cli import app

if __name__ == "__main__":
    app(prog_name="openwarframe")
