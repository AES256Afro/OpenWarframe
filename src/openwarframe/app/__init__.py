"""Desktop app: a local window with sortable, filterable views of the account."""

from .data import build_app_data
from .server import run_app

__all__ = ["build_app_data", "run_app"]


def main() -> None:
    """Entry point for the windowless ``openwarframe-app`` launcher.

    It has no console, so warnings and crashes go to <data folder>/logs/openwarframe.log.
    """
    from ..config import default_home
    from ..logs import setup_logging

    setup_logging(default_home())
    run_app()
