"""
Conversational chat management with history
"""
from typing import List, Dict, Optional
from datetime import datetime
import uuid


class ConversationManager:
    """Manages conversation history"""
    
    def __init__(self):
        self.conversations: Dict[str, List[Dict]] = {}
    
    def create_conversation(self) -> str:
        """Create a new conversation ID"""
        conv_id = str(uuid.uuid4())
        self.conversations[conv_id] = []
        return conv_id
    
    def add_message(self, conv_id: str, role: str, content: str):
        """Add a message to conversation history"""
        if conv_id not in self.conversations:
            self.conversations[conv_id] = []
        
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        self.conversations[conv_id].append(message)
    
    def get_history(self, conv_id: str, max_messages: int = 10) -> List[Dict]:
        """Get conversation history (last N messages)"""
        if conv_id not in self.conversations:
            return []
        
        messages = self.conversations[conv_id]
        # Return last max_messages (keep recent context)
        return messages[-max_messages:] if len(messages) > max_messages else messages
    
    def clear_history(self, conv_id: str):
        """Clear conversation history"""
        if conv_id in self.conversations:
            self.conversations[conv_id] = []


# Global conversation manager
conversation_manager = ConversationManager()
