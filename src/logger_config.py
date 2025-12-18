import logging
import sys

def setup_logger(name=None):
    """
    Configures a logger with the requested color scheme and format.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG) 
    
    if logger.hasHandlers():
        logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    
    try:
        import colorlog
        # Define Color Scheme
        log_colors = {
            'DEBUG': 'white',
            'INFO': 'cyan',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'bold_red',
        }
        formatter = colorlog.ColoredFormatter(
            "%(log_color)s[%(asctime)s] [%(levelname)s] [%(module)s]: %(message)s",
            datefmt='%Y-%m-%d %H:%M:%S',
            reset=True,
            log_colors=log_colors
        )
    except ImportError:
        # Fallback if colorlog is missing
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(module)s]: %(message)s",
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger

# Create a default instance for easy import
logger = setup_logger("SaxoBot")
