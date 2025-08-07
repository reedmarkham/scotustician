import signal
import threading
import logging

logger = logging.getLogger(__name__)

shutdown_requested = threading.Event()
active_futures = set()
executor_lock = threading.Lock()

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name} signal. Initiating graceful shutdown...")
    shutdown_requested.set()

def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    logger.info("Signal handlers configured for graceful shutdown")