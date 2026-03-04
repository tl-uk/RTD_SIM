"""
ui/log_capture.py

Captures all terminal output during Streamlit execution and saves to a file.
This helps with debugging when terminal scrollback is limited.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

class LogCapture:
    """Captures all logging output to both console and file."""
    
    def __init__(self, log_dir="logs"):
        """
        Initialize log capture.
        
        Args:
            log_dir: Directory to save log files (default: "logs")
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        # Create log filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"simulation_{timestamp}.log"
        
        self.setup_logging()
    
    def setup_logging(self):
        """Configure logging to output to both console and file."""
        
        # Get root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        
        # Remove existing handlers
        root_logger.handlers.clear()
        
        # Create formatters
        detailed_formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        console_formatter = logging.Formatter(
            '%(levelname)s:%(name)s:%(message)s'
        )
        
        # Console handler (existing behavior)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
        
        # File handler (detailed logs)
        file_handler = logging.FileHandler(self.log_file, mode='w', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)  # Capture everything
        file_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(file_handler)
        
        # Log the start
        root_logger.info("="*80)
        root_logger.info(f"Log capture initialized: {self.log_file}")
        root_logger.info("="*80)
    
    def get_log_path(self):
        """Return the path to the current log file."""
        return str(self.log_file)
    
    def add_separator(self, title=""):
        """Add a visual separator to the logs."""
        logger = logging.getLogger(__name__)
        logger.info("="*80)
        if title:
            logger.info(title)
            logger.info("="*80)


def init_log_capture():
    """
    Initialize log capture for the simulation.
    Call this once at the start of your Streamlit app.
    
    Returns:
        LogCapture instance
    """
    return LogCapture()


# Example usage in streamlit_app.py:
"""
from ui.log_capture import init_log_capture

# At the top of streamlit_app.py, after imports:
if 'log_capture' not in st.session_state:
    st.session_state.log_capture = init_log_capture()

# Show log file location in sidebar:
with st.sidebar:
    st.info(f"📄 Logs: {st.session_state.log_capture.get_log_path()}")
"""