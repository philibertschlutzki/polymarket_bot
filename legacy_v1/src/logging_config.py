import logging
import os


def setup_api_logging():
    """Setup dedicated API usage logger."""

    # Dedicated API logger
    api_logger = logging.getLogger("api_metrics")
    api_logger.setLevel(logging.INFO)

    # Ensure logs directory exists
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # File handler for API metrics
    api_handler = logging.FileHandler(os.path.join(log_dir, "gemini_api_usage.log"))
    api_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    api_handler.setFormatter(api_formatter)

    # Avoid adding multiple handlers if setup is called multiple times
    if not api_logger.handlers:
        api_logger.addHandler(api_handler)

    return api_logger
