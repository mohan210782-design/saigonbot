"""
Structured logging configuration
Provides JSON-formatted logs with request tracking
"""
import logging
import json
import sys
from datetime import datetime
from typing import Dict, Any, Optional
import uuid


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging"""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON"""
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add extra fields if present
        if hasattr(record, 'request_id'):
            log_data['request_id'] = record.request_id
        if hasattr(record, 'session_id'):
            log_data['session_id'] = record.session_id
        if hasattr(record, 'intent'):
            log_data['intent'] = record.intent
        if hasattr(record, 'latency_ms'):
            log_data['latency_ms'] = record.latency_ms
        if hasattr(record, 'retrieved_count'):
            log_data['retrieved_count'] = record.retrieved_count
        if hasattr(record, 'error_type'):
            log_data['error_type'] = record.error_type
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


def setup_logging(log_level: str = "INFO", use_json: bool = True):
    """
    Setup structured logging
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        use_json: Whether to use JSON formatting
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    
    # Set formatter
    if use_json:
        formatter = StructuredFormatter()
    else:
        formatter = logging.Formatter(
            '%(asctime)s %(levelname)s %(name)s - %(message)s'
        )
    
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Set levels for noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


class RequestLogger:
    """Context manager for request logging"""
    
    def __init__(self, logger: logging.Logger, request_id: Optional[str] = None):
        self.logger = logger
        self.request_id = request_id or str(uuid.uuid4())
        self.start_time = None
    
    def __enter__(self):
        self.start_time = datetime.now()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            latency_ms = (datetime.now() - self.start_time).total_seconds() * 1000
            self.logger.info(
                f"Request completed",
                extra={'request_id': self.request_id, 'latency_ms': latency_ms}
            )
    
    def log_request(self, **kwargs):
        """Log request with extra context"""
        self.logger.info(
            "Request received",
            extra={'request_id': self.request_id, **kwargs}
        )
    
    def log_response(self, **kwargs):
        """Log response with extra context"""
        if self.start_time:
            latency_ms = (datetime.now() - self.start_time).total_seconds() * 1000
            kwargs['latency_ms'] = latency_ms
        
        self.logger.info(
            "Response sent",
            extra={'request_id': self.request_id, **kwargs}
        )
    
    def log_error(self, error: Exception, **kwargs):
        """Log error with extra context"""
        self.logger.error(
            f"Error: {str(error)}",
            extra={
                'request_id': self.request_id,
                'error_type': type(error).__name__,
                **kwargs
            },
            exc_info=True
        )
