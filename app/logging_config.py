"""
Logging configuration for the app.
Ensures both structlog and standard library logging work together.
"""
import logging
import sys


def setup_logging(log_level: str = "INFO"):
    """Configure standard library logging to output properly."""
    # Convert string level to numeric
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure root logger
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        stream=sys.stdout,
        force=True  # Override any existing config
    )

    # Ensure our custom loggers are at the right level
    for logger_name in [
        'app.agents.graph',
        'app.agents.router',
        'app.agents.booking',
        'app.agents.response',
        'app.services.conversation',
    ]:
        logger = logging.getLogger(logger_name)
        logger.setLevel(numeric_level)
        # Ensure propagation to root logger
        logger.propagate = True

    # Reduce noise from external libraries
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    logging.getLogger('openai').setLevel(logging.WARNING)

    logging.info("Logging configured at level: %s", log_level)
