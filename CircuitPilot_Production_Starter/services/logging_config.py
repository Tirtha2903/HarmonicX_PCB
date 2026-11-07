import logging
from pathlib import Path

# Sentinel so that repeated imports (or Streamlit hot-reloads) do not duplicate handlers.
_logging_configured = False

# Resolve log directory relative to this file's package root, not the CWD.
_DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def configure_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    global _logging_configured
    if _logging_configured:
        return
    _logging_configured = True

    resolved_log_dir = log_dir if log_dir is not None else _DEFAULT_LOG_DIR
    resolved_log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(resolved_log_dir / "circuitpilot.log", encoding="utf-8"),
        ],
        force=True,
    )
