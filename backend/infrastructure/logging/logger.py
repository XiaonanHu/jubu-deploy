import sys
import traceback
from pathlib import Path

from loguru import logger

# Remove default handler
logger.remove()

# Set up default logging format with colors
LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

# Add console handler with custom format
logger.add(sys.stderr, format=LOG_FORMAT, level="INFO", colorize=True)


def get_project_root() -> Path:
    """Get the project root directory based on the current file's location."""
    return (
        Path(__file__).resolve().parent.parent
    )  # Adjust as necessary based on your structure


def setup_file_logging(log_dir="logs"):
    """Set up file logging with rotation"""
    project_root = get_project_root()  # Get the project root dynamically
    logs_path = project_root / log_dir
    logs_path.mkdir(parents=True, exist_ok=True)

    # Add file handler with rotation
    log_file = logs_path / "app.log"
    logger.add(
        str(log_file),
        rotation="10 MB",
        retention="1 month",
        compression="zip",
        format=LOG_FORMAT,
        level="DEBUG",
        backtrace=True,  # Enable backtrace
        diagnose=True,  # Enable diagnose
    )

    return logs_path


# Set up file logging
log_dir = setup_file_logging()


# Function to get a logger for a specific module
def get_logger(name):
    """Get a logger instance for a specific module"""
    return logger.bind(name=name)


# Add an exception handler to capture and log full stack traces
def log_exception(exc_type, exc_value, exc_traceback):
    """Log an exception with full traceback"""
    if issubclass(exc_type, KeyboardInterrupt):
        # Don't log keyboard interrupt exceptions
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # Get the full traceback as a string
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
    tb_text = "".join(tb_lines)

    # Log the full traceback
    logger.opt(exception=False).error(f"Uncaught exception:\n{tb_text}")


# Set the exception hook
sys.excepthook = log_exception
