"""
Custom error classes for the chatbot system
Provides user-friendly error messages and proper error handling
"""
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class ChatbotError(Exception):
    """Base exception for chatbot errors"""
    
    def __init__(self, message: str, user_message: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.user_message = user_message or "I'm having a bit of trouble right now. Please try again in a moment, or call us at +84 (028) 6291 3672 for immediate assistance. 😊"
        self.details = details or {}
        super().__init__(self.message)


class RetrievalError(ChatbotError):
    """Error during retrieval from vector database"""
    
    def __init__(self, message: str, query: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        user_message = "I couldn't find that in our current menu, but I'd be happy to suggest something similar. Could you tell me what type of dish you're looking for? 😊"
        super().__init__(message, user_message, details)
        self.query = query


class LLMError(ChatbotError):
    """Error during LLM generation"""
    
    def __init__(self, message: str, model: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        user_message = "I'm having trouble generating a response right now. Please try rephrasing your question, or call us at +84 (028) 6291 3672 for immediate assistance. 😊"
        super().__init__(message, user_message, details)
        self.model = model


class IntentError(ChatbotError):
    """Error during intent classification"""
    
    def __init__(self, message: str, query: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        user_message = "I'd love to help you! Could you tell me a bit more about what you're looking for? 😊"
        super().__init__(message, user_message, details)
        self.query = query


class DatabaseError(ChatbotError):
    """Error during database operations"""
    
    def __init__(self, message: str, operation: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        user_message = "I'm having trouble accessing conversation history. Your query will still be processed, but I may not have access to previous messages. 😊"
        super().__init__(message, user_message, details)
        self.operation = operation


class ValidationError(ChatbotError):
    """Error during input validation"""
    
    def __init__(self, message: str, field: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        user_message = "I didn't quite understand that. Could you rephrase your question? 😊"
        super().__init__(message, user_message, details)
        self.field = field


class SystemError(ChatbotError):
    """General system error"""
    
    def __init__(self, message: str, component: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        user_message = "I'm experiencing a technical issue right now. Please try again in a moment, or call us at +84 (028) 6291 3672 for immediate assistance. 😊"
        super().__init__(message, user_message, details)
        self.component = component


def handle_error(error: Exception, context: Optional[Dict[str, Any]] = None) -> str:
    """
    Handle errors and return user-friendly message.
    
    Args:
        error: The exception that occurred
        context: Additional context about the error
        
    Returns:
        User-friendly error message
    """
    context = context or {}
    
    # Log the error with full details
    logger.error(f"Error occurred: {type(error).__name__}: {str(error)}", extra={
        "error_type": type(error).__name__,
        "error_message": str(error),
        **context
    })
    
    # Return user-friendly message based on error type
    if isinstance(error, ChatbotError):
        return error.user_message
    
    # Handle specific exception types
    if isinstance(error, ConnectionError):
        return "I'm having trouble connecting to our services. Please try again in a moment. 😊"
    
    if isinstance(error, TimeoutError):
        return "The request is taking longer than expected. Please try again. 😊"
    
    if isinstance(error, ValueError):
        return "I didn't quite understand that. Could you rephrase your question? 😊"
    
    if isinstance(error, KeyError):
        return "I'm missing some information. Could you provide more details? 😊"
    
    # Generic fallback
    return "I'm having a bit of trouble right now. Please try again in a moment, or call us at +84 (028) 6291 3672 for immediate assistance. 😊"
