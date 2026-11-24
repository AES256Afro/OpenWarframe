"""Desktop app: a local window with sortable, filterable views of the account."""

from .data import build_app_data
from .server import run_app

__all__ = ["build_app_data", "run_app"]


def main() -> None:
    """Entry point for the windowless ``openwarframe-app`` launcher."""
    run_app()
