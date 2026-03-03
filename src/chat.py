"""
Conversational chat management with history
Uses persistent database storage
"""
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import uuid
import logging

from database import get_db

logger = logging.getLogger(__name__)


class ConversationManager:
    """Manages conversation history with persistent storage"""
    
    def __init__(self):
        self.db = get_db()
        # Session timeout: 30 minutes of inactivity
        self.session_timeout_minutes = 30
    
    def create_conversation(self, session_id: Optional[str] = None) -> str:
        """Create a new conversation ID"""
        conv_id = self.db.create_conversation(session_id=session_id)
        logger.debug(f"Created conversation {conv_id}")
        return conv_id
    
    def get_or_create_conversation(self, session_id: str) -> str:
        """Get existing conversation by session_id or create new one"""
        try:
            conv = self.db.get_conversation_by_session(session_id)
            
            if conv:
                # Check if session is still active (within timeout)
                updated_at_str = conv['updated_at']
                # Handle different datetime formats
                if 'T' in updated_at_str:
                    updated_at = datetime.fromisoformat(updated_at_str.replace('Z', '').split('.')[0])
                else:
                    updated_at = datetime.fromisoformat(updated_at_str)
                
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=None)
                
                time_diff = datetime.now() - updated_at
                
                if time_diff < timedelta(minutes=self.session_timeout_minutes):
                    logger.debug(f"Resuming conversation {conv['id']}")
                    return conv['id']
                else:
                    logger.debug(f"Session expired, creating new conversation")
            
            # Create new conversation
            return self.db.create_conversation(session_id=session_id)
        except Exception as e:
            logger.error(f"Error in get_or_create_conversation: {e}")
            # Fallback: create new conversation
            return self.db.create_conversation(session_id=session_id)
    
    def add_message(
        self,
        conv_id: str,
        role: str,
        content: str,
        intent: Optional[str] = None,
        metadata: Optional[Dict] = None
    ):
        """Add a message to conversation history"""
        # Ensure conversation exists
        if not self.db.get_conversation_by_session(conv_id):
            # Try to get by conversation ID
            # If doesn't exist, create it
            pass
        
        message_id = self.db.add_message(
            conversation_id=conv_id,
            role=role,
            content=content,
            intent=intent,
            metadata=metadata
        )
        logger.debug(f"Added message {message_id} to conversation {conv_id}")
    
    def get_history(self, conv_id: str, max_messages: int = 10) -> List[Dict]:
        """Get conversation history (last N messages)"""
        messages = self.db.get_messages(conv_id, max_messages=max_messages)
        
        # Convert to format expected by RAG pipeline
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                "role": msg['role'],
                "content": msg['content'],
                "timestamp": msg['timestamp']
            })
        
        return formatted_messages
    
    def clear_history(self, conv_id: str):
        """Clear conversation history (deactivate conversation)"""
        # Instead of deleting, deactivate the conversation
        self.db.update_conversation(conv_id, metadata={"deactivated": True})
        logger.info(f"Cleared history for conversation {conv_id}")
    
    def get_conversation_summary(self, conv_id: str) -> Optional[str]:
        """Get summary of conversation for long sessions"""
        return self.db.get_conversation_summary(conv_id)


# Global conversation manager
conversation_manager = ConversationManager()
