import logging
from logging.handlers import RotatingFileHandler
from .config import Config

def setup_logging(config: Config) -> logging.Logger:
    """Configure application logging"""
    logger = logging.getLogger('pm2_controller')
    logger.setLevel(getattr(logging, config.LOG_LEVEL))
    
    # Create formatters and handlers
    formatter = logging.Formatter(config.LOG_FORMAT)
    
    # File handler
    file_handler = RotatingFileHandler(
        config.LOG_FILE,
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger