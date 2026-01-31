import json
import logging
import logging.handlers
import pathlib
import traceback
import sys
import os
from datetime import datetime, timezone

# Ensure logs directory exists
log_dir = pathlib.Path('logs')
log_dir.mkdir(exist_ok=True)

# Log file path
error_log_file = log_dir / 'errors.log'

# Configure separate logger for errors
error_logger = logging.getLogger('error_logger')
error_logger.setLevel(logging.WARNING) # Capture WARNING, ERROR, CRITICAL
error_logger.propagate = False  # Prevent propagation to root logger to avoid duplicates

# Handler for error log file with rotation
handler = logging.handlers.RotatingFileHandler(
    str(error_log_file),
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,
    encoding='utf-8',
    delay=True
)

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }

        # Merge extra fields if they exist
        if hasattr(record, 'custom_fields'):
            log_entry.update(record.custom_fields)

        return json.dumps(log_entry)

handler.setFormatter(JsonFormatter())
error_logger.addHandler(handler)

def log_error(level, category, component, message, error=None, context=None):
    """
    General structured error logging.
    """
    custom_fields = {
        "category": category,
        "component": component,
        "error_type": type(error).__name__ if error else None,
        "stack_trace": traceback.format_exc() if error else None,
        "context": context or {}
    }

    if level.upper() == "CRITICAL":
        error_logger.critical(message, extra={"custom_fields": custom_fields})
    elif level.upper() == "WARNING":
        error_logger.warning(message, extra={"custom_fields": custom_fields})
    else:
        error_logger.error(message, extra={"custom_fields": custom_fields})

def log_api_error(api_name, endpoint, error, response_code=None, context=None):
    """
    Specific logger for API errors.
    """
    ctx = context or {}
    if response_code:
        ctx['response_code'] = response_code

    log_error(
        level="ERROR",
        category="api",
        component=f"{api_name}_client",
        message=f"API Request failed: {endpoint}",
        error=error,
        context=ctx
    )

def log_git_error(operation, error, context=None):
    """
    Specific logger for Git errors.
    """
    log_error(
        level="WARNING", # Git errors are usually not fatal for the main loop
        category="system",
        component="git_integration",
        message=f"Git operation '{operation}' failed",
        error=error,
        context=context
    )

def log_database_error(operation, error, context=None):
    """
    Specific logger for Database errors.
    """
    log_error(
        level="CRITICAL",
        category="database",
        component="sqlite",
        message=f"Database operation '{operation}' failed",
        error=error,
        context=context
    )
