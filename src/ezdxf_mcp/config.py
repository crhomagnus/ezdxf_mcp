"""Environment-backed server configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    workspace: Path
    max_docs: int = 8
    max_file_mb: int = 500
    default_timeout: float = 60.0
    default_gap_tol: float = 0.01
    respect_layer_state: bool = True
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> Settings:
        workspace = Path(
            os.path.expanduser(os.getenv("EZDXF_MCP_WORKSPACE", "~/dxf-workspace"))
        ).resolve()
        return cls(
            workspace=workspace,
            max_docs=int(os.getenv("EZDXF_MCP_MAX_DOCS", "8")),
            max_file_mb=int(os.getenv("EZDXF_MCP_MAX_FILE_MB", "500")),
            default_timeout=float(os.getenv("EZDXF_MCP_DEFAULT_TIMEOUT", "60")),
            default_gap_tol=float(os.getenv("EZDXF_MCP_DEFAULT_GAP_TOL", "0.01")),
            respect_layer_state=_env_bool("EZDXF_MCP_RESPECT_LAYER_STATE", True),
            log_level=os.getenv("EZDXF_MCP_LOG_LEVEL", "INFO").upper(),
        )


settings = Settings.from_env()
