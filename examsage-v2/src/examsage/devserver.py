"""Factory for the existing Uvicorn reloader, used only by the local test entry."""
from pathlib import Path

from .library import create_library_app


def create_app():
    return create_library_app(Path(__file__).resolve().parents[2] / 'data' / 'grt')
