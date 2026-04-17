"""Central logging configuration for PaperManager backend."""
import logging
import logging.handlers
from pathlib import Path

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_LOG_FILE = _LOG_DIR / "app.log"

_FMT = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
_DATE = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """Call once at startup to configure the root logger."""
    root = logging.getLogger()
    if root.handlers:
        return  # already configured (e.g. during tests)

    root.setLevel(level)

    # Console handler — same output you already see from uvicorn
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter(_FMT, datefmt=_DATE))
    root.addHandler(console)

    # Rotating file handler — max 5 MB, keep 3 backups
    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATE))
    root.addHandler(file_handler)

    # Quieten noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
