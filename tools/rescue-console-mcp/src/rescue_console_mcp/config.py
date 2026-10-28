from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CONNECTOR_ROOT = Path(
    r"C:\Users\redma\Workworkworkworkworkwork\auto-tickets\logmein-connector"
)


@dataclass(frozen=True)
class Settings:
    connector_root: Path
    env_file: Path

    @classmethod
    def from_env(cls) -> "Settings":
        connector_root = Path(
            os.path.expandvars(
                os.path.expanduser(
                    os.getenv("RESCUE_CONNECTOR_ROOT", str(DEFAULT_CONNECTOR_ROOT))
                )
            )
        ).resolve()
        env_file = Path(
            os.path.expandvars(
                os.path.expanduser(
                    os.getenv("RESCUE_ENV_FILE", str(connector_root / ".env"))
                )
            )
        ).resolve()
        return cls(
            connector_root=connector_root,
            env_file=env_file,
        )
