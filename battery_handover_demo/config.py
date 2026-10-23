"""Application configuration with safe local defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = PACKAGE_DIR / "data"
DEFAULT_DATABASE_PATH = DEFAULT_DATA_DIR / "demo.db"


def _env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings.

    The default database lives inside the package's ``data`` directory. Tests
    can pass a different URL to :func:`database.build_engine` without mutating
    global process state.
    """

    database_url: str
    database_echo: bool = False


settings = Settings(
    database_url=os.getenv(
        "BATTERY_HANDOVER_DATABASE_URL",
        f"sqlite+pysqlite:///{DEFAULT_DATABASE_PATH.as_posix()}",
    ),
    database_echo=_env_flag("BATTERY_HANDOVER_DATABASE_ECHO"),
)
