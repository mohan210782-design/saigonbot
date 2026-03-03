"""
Database module for persistent conversation storage
Uses SQLite for simplicity, can be migrated to PostgreSQL later
"""
import sqlite3
import json
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from pathlib import Path
import uuid
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)


class ConversationDB:
    """Database operations for conversations"""
    
    def __init__(self, db_path: str = "conversations.db"):
        """Initialize database connection"""
        self.db_path = db_path
        self._init_database()
    
    def _get_db_path(self) -> Path:
        """Get full path to database file"""
        # Store in project root
        project_root = Path(__file__).parent.parent
        return project_root / self.db_path
    
    def _init_database(self):
        """Initialize database schema"""
        db_file = self._get_db_path()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Conversations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    session_id TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT,
                    is_active INTEGER DEFAULT 1
                )
            """)
            
            # Messages table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    intent TEXT,
                    metadata TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                )
            """)
            
            # User preferences table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id TEXT PRIMARY KEY,
                    dietary_preferences TEXT,
                    spice_level TEXT,
                    favorite_items TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_session_id ON conversations(session_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_updated_at ON conversations(updated_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)")
            
            conn.commit()
            logger.info(f"Database initialized at {db_file}")
    
    @contextmanager
    def _get_connection(self):
        """Get database connection with proper cleanup"""
        db_file = self._get_db_path()
        conn = sqlite3.connect(str(db_file), check_same_thread=False)
        conn.row_factory = sqlite3.Row  # Return rows as dict-like objects
        try:
            yield conn
        finally:
            conn.close()
    
    def create_conversation(self, session_id: Optional[str] = None, user_id: Optional[str] = None, metadata: Optional[Dict] = None) -> str:
        """Create a new conversation"""
        session_id = session_id or str(uuid.uuid4())
        
        # Check if conversation with this session_id already exists
        existing = self.get_conversation_by_session(session_id)
        if existing:
            logger.debug(f"Conversation already exists for session {session_id}: {existing['id']}")
            return existing['id']
        
        conv_id = str(uuid.uuid4())
        metadata_json = json.dumps(metadata) if metadata else None
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO conversations (id, user_id, session_id, metadata)
                VALUES (?, ?, ?, ?)
            """, (conv_id, user_id, session_id, metadata_json))
            conn.commit()
        
        logger.debug(f"Created conversation {conv_id} with session {session_id}")
        return conv_id
    
    def get_conversation_by_session(self, session_id: str) -> Optional[Dict]:
        """Get conversation by session ID"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM conversations WHERE session_id = ? AND is_active = 1
            """, (session_id,))
            row = cursor.fetchone()
            
            if row:
                conv = dict(row)
                if conv.get('metadata'):
                    conv['metadata'] = json.loads(conv['metadata'])
                return conv
        return None
    
    def update_conversation(self, conv_id: str, metadata: Optional[Dict] = None):
        """Update conversation metadata and timestamp"""
        metadata_json = json.dumps(metadata) if metadata else None
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if metadata_json:
                cursor.execute("""
                    UPDATE conversations 
                    SET updated_at = CURRENT_TIMESTAMP, metadata = ?
                    WHERE id = ?
                """, (metadata_json, conv_id))
            else:
                cursor.execute("""
                    UPDATE conversations 
                    SET updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (conv_id,))
            conn.commit()
    
    def deactivate_old_conversations(self, hours: int = 24):
        """Deactivate conversations older than specified hours"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE conversations 
                SET is_active = 0
                WHERE updated_at < ? AND is_active = 1
            """, (cutoff_time.isoformat(),))
            conn.commit()
            
            count = cursor.rowcount
            logger.info(f"Deactivated {count} old conversations")
    
    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        intent: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> str:
        """Add a message to conversation"""
        message_id = str(uuid.uuid4())
        metadata_json = json.dumps(metadata) if metadata else None
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO messages (id, conversation_id, role, content, intent, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (message_id, conversation_id, role, content, intent, metadata_json))
            
            # Update conversation timestamp
            cursor.execute("""
                UPDATE conversations 
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (conversation_id,))
            
            conn.commit()
        
        logger.debug(f"Added message {message_id} to conversation {conversation_id}")
        return message_id
    
    def get_messages(self, conversation_id: str, max_messages: int = 10) -> List[Dict]:
        """Get messages for a conversation"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM messages 
                WHERE conversation_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (conversation_id, max_messages))
            
            rows = cursor.fetchall()
            messages = []
            for row in reversed(rows):  # Reverse to get chronological order
                msg = dict(row)
                if msg.get('metadata'):
                    msg['metadata'] = json.loads(msg['metadata'])
                messages.append(msg)
            
            return messages
    
    def get_conversation_summary(self, conversation_id: str) -> Optional[str]:
        """Get summary of conversation (for long conversations)"""
        messages = self.get_messages(conversation_id, max_messages=50)
        
        if len(messages) < 10:
            return None
        
        # Simple summary: first few and last few messages
        summary_parts = []
        summary_parts.append(f"Conversation started with: {messages[0].get('content', '')[:100]}")
        summary_parts.append(f"... ({len(messages) - 4} messages in between) ...")
        summary_parts.append(f"Recent context: {messages[-3].get('content', '')[:100]}")
        
        return " | ".join(summary_parts)
    
    def set_user_preferences(
        self,
        user_id: str,
        dietary_preferences: Optional[List[str]] = None,
        spice_level: Optional[str] = None,
        favorite_items: Optional[List[str]] = None
    ):
        """Set or update user preferences"""
        dietary_json = json.dumps(dietary_preferences) if dietary_preferences else None
        favorites_json = json.dumps(favorite_items) if favorite_items else None
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_preferences 
                (user_id, dietary_preferences, spice_level, favorite_items, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    dietary_preferences = COALESCE(excluded.dietary_preferences, dietary_preferences),
                    spice_level = COALESCE(excluded.spice_level, spice_level),
                    favorite_items = COALESCE(excluded.favorite_items, favorite_items),
                    updated_at = CURRENT_TIMESTAMP
            """, (user_id, dietary_json, spice_level, favorites_json))
            conn.commit()
    
    def get_user_preferences(self, user_id: str) -> Optional[Dict]:
        """Get user preferences"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM user_preferences WHERE user_id = ?
            """, (user_id,))
            row = cursor.fetchone()
            
            if row:
                prefs = dict(row)
                if prefs.get('dietary_preferences'):
                    prefs['dietary_preferences'] = json.loads(prefs['dietary_preferences'])
                if prefs.get('favorite_items'):
                    prefs['favorite_items'] = json.loads(prefs['favorite_items'])
                return prefs
        return None
    
    def cleanup_old_data(self, days: int = 90):
        """Delete conversations older than specified days"""
        cutoff_time = datetime.now() - timedelta(days=days)
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM conversations 
                WHERE updated_at < ?
            """, (cutoff_time.isoformat(),))
            conn.commit()
            
            count = cursor.rowcount
            logger.info(f"Deleted {count} old conversations")


# Global database instance
_db_instance = None


def get_db() -> ConversationDB:
    """Get or create global database instance"""
    global _db_instance
    if _db_instance is None:
        _db_instance = ConversationDB()
    return _db_instance
