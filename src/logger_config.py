import logging
import sys
import colorlog

def setup_logger(name=None):
    """
    Configures a logger with the requested color scheme and format.
    
    Styles:
    DEBUG (White): Low-level ticks
    INFO (Cyan): Scanner updates
    WARNING (Yellow): Peaks
    ERROR (Red): API Errors
    CRITICAL (Bold Red): Trade Execution
    """
    
    # Define Color Scheme
    log_colors = {
        'DEBUG': 'white',
        'INFO': 'cyan',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'bold_red',
    }

    # Define Format
    # User Request: [%(asctime)s] [%(levelname)s] [%(module)s]: %(message)s
    # We add %(log_color)s to apply colors
    formatter = colorlog.ColoredFormatter(
        "%(log_color)s[%(asctime)s] [%(levelname)s] [%(module)s]: %(message)s",
        datefmt='%Y-%m-%d %H:%M:%S',
        reset=True,
        log_colors=log_colors
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG) # Catch all, filter later if needed
    
    # Remove existing handlers to avoid duplicates (if re-importing)
    if logger.hasHandlers():
        logger.handlers.clear()
        
    logger.addHandler(handler)
    
    return logger

# Create a default instance for easy import
# e.g. from logger_config import logger
logger = setup_logger("SaxoBot")
