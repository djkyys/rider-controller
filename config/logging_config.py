"""
Shared logging configuration for all services.
Place in: ~/rider-controller/config/logging_config.py
"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

# Configuration - can be overridden by environment variables
LOG_DIR = Path.home() / "rider-controller" / "logs"
LOG_LEVEL = logging.INFO

def setup_logger(service_name: str, log_file: str = None):
    """
    Setup standardized logger for any service.
    
    Args:
        service_name: Name of the service (e.g., 'main', 'obd', 'camera')
        log_file: Optional specific log file name (defaults to service_name.log)
    
    Returns:
        Logger instance
    """
    
    # Create logs directory if it doesn't exist
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    # Determine log file path
    if log_file is None:
        log_file = f"{service_name}.log"
    log_path = LOG_DIR / log_file
    
    # Create logger
    logger = logging.getLogger(service_name)
    logger.setLevel(LOG_LEVEL)
    
    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # Console handler (stdout) - for systemd journal
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(LOG_LEVEL)
    console_formatter = logging.Formatter(
        f'[%(asctime)s] [{service_name}] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # File handler - rotating log files (10MB max, keep 5 backups)
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(LOG_LEVEL)
    file_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    logger.info(f"Logger initialized - File: {log_path}")
    
    return logger

# Example usage in any service:
# from config.logging_config import setup_logger
# logger = setup_logger('obd')
# logger.info("OBD service started")
# logger.error("Connection failed")
