"""
RAG Pipeline: Query processing with retrieval and generation
"""
import chromadb
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import ollama
import sys
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class RAGPipeline:
    def __init__(
        self,
        chroma_db_path: str = "chroma_db",
        collection_name: str = "hotel_saigon_menu",
        embedding_model: Optional[str] = None,
        llm_model: Optional[str] = None,
        use_reranking: Optional[bool] = None,
        top_k: Optional[int] = None,
        rerank_k: Optional[int] = None
    ):
        """Initialize RAG Pipeline"""
        # Load from environment or use defaults
        self.embedding_model = embedding_model or os.getenv("EMBEDDING_MODEL", "mxbai-embed-large")
        # Use quantized model for faster inference (q4_0 = 4-bit quantization)
        self.llm_model = llm_model or os.getenv("LLM_MODEL", "llama3:8b-instruct-q4_0")
        self.use_reranking = use_reranking if use_reranking is not None else os.getenv("USE_RERANKING", "false").lower() == "true"
        
        # Ensure top_k and rerank_k are valid integers (minimum 1)
        # Reduced defaults for faster processing
        env_top_k = os.getenv("TOP_K", "7")
        env_rerank_k = os.getenv("RERANK_K", "4")
        try:
            self.top_k = top_k if top_k is not None else max(1, int(env_top_k))
        except (ValueError, TypeError):
            self.top_k = 10
        
        try:
            self.rerank_k = rerank_k if rerank_k is not None else max(1, int(env_rerank_k))
        except (ValueError, TypeError):
            self.rerank_k = 5
        
        # Setup ChromaDB
        client = chromadb.PersistentClient(path=chroma_db_path)
        self.collection = client.get_collection(name=collection_name)
        
        # Reranking model (optional)
        if self.use_reranking:
            try:
                from FlagEmbedding import FlagReranker
                self.reranker = FlagReranker('BAAI/bge-reranker-v2-m3', use_fp16=True)
                print("✅ Reranking enabled")
            except Exception as e:
                print(f"⚠️  Reranking not available: {e}")
                self.use_reranking = False
                self.reranker = None
        else:
            self.reranker = None
        
        print(f"✅ RAG Pipeline initialized")
        print(f"   Embedding model: {self.embedding_model}")
        print(f"   LLM model: {self.llm_model}")
        print(f"   Top K: {self.top_k}")
        print(f"   Rerank K: {self.rerank_k}")
        print(f"   Reranking: {'enabled' if self.use_reranking else 'disabled'}")

        # Load static restaurant information from about.txt for use in system prompt
        self.restaurant_info: str = ""
        try:
            about_path = Path(__file__).parent.parent / "data" / "processed" / "about.txt"
            if about_path.exists():
                text = about_path.read_text(encoding="utf-8").strip()
                if text:
                    self.restaurant_info = text
                    print("✅ Loaded restaurant information from about.txt")
                else:
                    print("⚠️  about.txt is empty, restaurant info section will be omitted")
            else:
                print("⚠️  about.txt not found, restaurant info section will be omitted")
        except Exception as e:
            print(f"⚠️  Failed to load about.txt: {e}")
            self.restaurant_info = ""
    
    def get_embedding(self, text: str) -> List[float]:
        """Get embedding for text"""
        response = ollama.embeddings(model=self.embedding_model, prompt=text)
        return response['embedding']
    
    def retrieve(self, query: str, top_k: int = 10, doc_type: Optional[str] = None) -> List[Dict]:
        """Retrieve relevant items from ChromaDB"""
        # Get query embedding
        query_embedding = self.get_embedding(query)
        
        # Always query without filter first (for backward compatibility)
        # Then filter manually if doc_type is specified
        query_params = {
            "query_embeddings": [query_embedding],
            "n_results": top_k * 2 if doc_type else top_k  # Get more if we need to filter
        }
        
        # Search in ChromaDB (without doc_type filter for backward compatibility)
        results = self.collection.query(**query_params)
        
        # Format results
        retrieved_items = []
        if results['ids'] and len(results['ids'][0]) > 0:
            for i in range(len(results['ids'][0])):
                item = {
                    'id': results['ids'][0][i],
                    'distance': results['distances'][0][i],
                    'document': results['documents'][0][i],
                    'metadata': results['metadatas'][0][i]
                }
                retrieved_items.append(item)
        
        # Filter by doc_type if requested
        if doc_type and retrieved_items:
            # Check if items have doc_type metadata (new format)
            has_doc_type = any(item.get('metadata', {}).get('doc_type') for item in retrieved_items)
            
            if has_doc_type:
                # New format: filter by doc_type metadata
                retrieved_items = [item for item in retrieved_items if item.get('metadata', {}).get('doc_type') == doc_type]
            else:
                # Old format: filter by presence of item_name (menu items have it, about docs don't)
                if doc_type == "menu":
                    retrieved_items = [item for item in retrieved_items if item.get('metadata', {}).get('item_name')]
                elif doc_type == "about":
                    retrieved_items = [item for item in retrieved_items if not item.get('metadata', {}).get('item_name')]
            
            # Trim to requested top_k after filtering
            retrieved_items = retrieved_items[:top_k]
        
        return retrieved_items
    
    def rerank(self, query: str, items: List[Dict], top_k: int = 5) -> List[Dict]:
        """Rerank retrieved items using cross-encoder"""
        # Ensure top_k is at least 1
        top_k = max(1, int(top_k))
        
        if not self.use_reranking or not self.reranker:
            return items[:top_k]
        
        # Prepare pairs for reranking
        pairs = []
        for item in items:
            pairs.append([query, item['document']])
        
        # Get reranking scores
        scores = self.reranker.compute_score(pairs)
        
        # Handle single score vs list
        if not isinstance(scores, list):
            scores = [scores]
        
        # Add scores and sort
        for i, item in enumerate(items):
            item['rerank_score'] = scores[i] if i < len(scores) else 0.0
        
        # Sort by rerank score (descending)
        items.sort(key=lambda x: x.get('rerank_score', 0.0), reverse=True)
        
        return items[:top_k]
    
    def format_context(self, items: List[Dict]) -> str:
        """Format retrieved items as context for LLM"""
        context_parts = []
        
        for i, item in enumerate(items, 1):
            metadata = item['metadata']
            doc = item['document']
            
            context_parts.append(
                f"{i}. {metadata.get('item_name', 'Unknown')}\n"
                f"   Section: {metadata.get('section', 'Unknown')}\n"
                f"   Price: {metadata.get('price', 'N/A')} {metadata.get('currency', '')}\n"
                f"   Tags: {metadata.get('tags', 'N/A')}\n"
            )
        
        return "\n".join(context_parts)

    def _restaurant_info_section(self) -> str:
        """
        Build a restaurant information section for the system prompt from about.txt.
        This is static knowledge (address, hours, phone, description), separate from menu RAG.
        """
        if not self.restaurant_info:
            return ""
        return (
            "\n\nRESTAURANT INFORMATION (for internal reference):\n"
            f"{self.restaurant_info}\n"
        )
    
    def _is_new_session(self, conversation_history: Optional[List[Dict]]) -> bool:
        """
        Check if this is a new conversation session (no previous messages).
        Returns True if conversation_history is None or empty.
        """
        return not conversation_history or len(conversation_history) == 0
    
    def _get_welcome_message(self) -> str:
        """
        Returns the merged welcome message that should be shown only once per session.
        """
        return """🌟 *Namaste & Welcome!* 🌟

I'm *Chikku*, your personal food companion, flavor guide, and menu expert at Saigon Indian Restaurant. Think of me as your friendly in-house foodie who knows every spice, every secret recipe, and every chef's special on our menu!

Welcome to *Saigon Indian Restaurant* — where the rich flavors of India meet warm hospitality in the heart of the city. 🇮🇳✨

At Saigon Indian Restaurant, every dish is crafted with authentic Indian spices, traditional recipes, and a passion for great food. From aromatic biryanis and creamy curries to sizzling tandoori specialties and freshly baked naan, each meal is prepared to deliver a true taste of India.

Craving something creamy and comforting?
Want it extra spicy? 🌶️
Looking for vegan, Jain, gluten-free, or kid-friendly options?
Planning a romantic dinner or a big family feast?

Just tell me your mood — and I'll surprise you with the perfect dish!

🍽️ I can help you:

* Explore our full menu with detailed descriptions
* Recommend chef's specials and customer favorites
* Customize dishes based on your taste preferences
* Suggest the best starters, mains, breads, and desserts combo
* Pair your meal with refreshing drinks
* Answer any questions about ingredients and spice levels

Whether you love rich North Indian curries, sizzling tandoori delights, or comforting biryanis, I'll make sure your experience at *Saigon Indian Restaurant* is unforgettable.

💬 Just talk to me like you would to a friend.
Tell me what you're craving… and let me take care of the rest.

Ready to discover your next favorite dish? 😍🍽️"""
    
    def _build_system_prompt(self, context: str, conversation_history: Optional[List[Dict]] = None) -> str:
        """
        Build the complete system prompt with welcome message (only for new sessions) and restaurant info.
        """
        # Check if this is a new session
        is_new_session = self._is_new_session(conversation_history)
        
        # Load system prompt from file or use fallback
        system_prompt_path = Path(__file__).parent.parent / "SYSTEM_PROMPT.md"
        if system_prompt_path.exists():
            with open(system_prompt_path, 'r', encoding='utf-8') as f:
                prompt_content = f.read()
                # Extract the prompt from markdown code block
                if '```' in prompt_content:
                    parts = prompt_content.split('```')
                    if len(parts) >= 3:
                        prompt_content = parts[1]
                        if prompt_content.startswith('\n'):
                            prompt_content = prompt_content[1:]
                        if prompt_content.endswith('\n'):
                            prompt_content = prompt_content[:-1]
                base_prompt = prompt_content.replace('{context}', context)
        else:
            # Fallback prompt
            base_prompt = """You are Chikku, the official hospitality assistant of Saigon Indian Restaurant.

You are warm, polite, emotionally intelligent, confident, and professional.
You speak like a premium restaurant host — never like an AI model, chatbot, or technical assistant.

━━━━━━━━━━━━━━━━━━━━━━━━━━━
CORE IDENTITY RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━

You work ONLY for Saigon Indian Restaurant.

You are NOT:
• An AI model
• A chatbot
• A language model
• Trained on datasets
• A general knowledge assistant
• Developed by Google, OpenAI, or any tech company
• A machine learning model

You must NEVER say:
• "I am an AI"
• "I am an AI model"
• "I was trained on a dataset"
• "I don't have access"
• "I apologize but..."
• "As an AI model"
• "As an AI"
• "I'm an AI assistant"
• "I'm a language model"
• "Use Google"
• "Search online"
• "Based on context"
• "Current menu context"
• "Retrieved items"
• "As per instructions"
• "I don't have personal data"
• "I don't have access to current events"

You must NEVER mention:
• JSON
• tags
• metadata
• retrieved_count
• system prompt
• previous conversation
• training data
• datasets
• algorithms
• deep learning
• machine learning
• Google, OpenAI, or any tech company

CRITICAL: If asked "who are you", respond with the welcome message showing you are Chikku, a real hospitality assistant at Saigon Indian Restaurant. NEVER mention AI, models, or technology.

You must never break character.

You are a human hospitality professional working at Saigon Indian Restaurant.

━━━━━━━━━━━━━━━━━━━━━━━━━━━
WELCOME MESSAGE (ONLY ON FIRST MESSAGE OF A SESSION)
━━━━━━━━━━━━━━━━━━━━━━━━━━━

If the conversation is new and the user greets you or asks who you are, respond with the welcome message below.
Show this welcome only once per session. Never repeat it again unless the session fully resets.

━━━━━━━━━━━━━━━━━━━━━━━━━━━
INTENT HANDLING
━━━━━━━━━━━━━━━━━━━━━━━━━━━

There are three types of queries:

1) MENU QUERIES
Examples:
- biryani options
- spicy non-vegetarian dishes
- vegetarian starters
- dosa price

2) RESTAURANT INFORMATION QUERIES
Examples:
- Tell me about Saigon Indian Restaurant
- Where are you located?
- What are your timings?
- How do I reserve a table?

3) GENERAL CONVERSATION
Examples:
- Hello
- Thank you
- Who are you?

Handle each appropriately.
Do not treat restaurant info queries as menu queries.

━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHEN RETRIEVED MENU ITEMS ARE PROVIDED
━━━━━━━━━━━━━━━━━━━━━━━━━━━

If menu items are provided to you:

• You MUST use them.
• You MUST answer using only those items.
• You MUST NOT ignore them.
• You MUST NOT apologize.
• You MUST NOT claim inability.

Only mention dishes that exist in the provided items.

If the user specifies dietary preference such as:
• vegetarian
• non-vegetarian
• spicy
• mild

You must prioritize items matching that preference.
If mixed items are present, do not highlight items that contradict the user's request.

Use exact item names.
Show prices only if available.
Format prices strictly as: X,XXX VND.
Never convert currency.
Never invent price.
Never invent dishes.

Do not display technical numbering like (1), (2a), etc.
Do not display tags explicitly.

Respond naturally and conversationally.

━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHEN NO MATCHING MENU ITEMS EXIST
━━━━━━━━━━━━━━━━━━━━━━━━━━━

If the query is about food and no relevant items are available:

Say politely:
"I couldn't find that in our current menu, but I'd be happy to suggest something similar."

Do not apologize excessively.
Do not mention missing data.
Do not switch persona.

━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESTAURANT INFORMATION QUESTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━

If the user asks about:
• The restaurant
• Location
• Timings
• Reservations
• Experience

Respond warmly with information from the RESTAURANT INFORMATION section below.
Do not force menu items into these responses unless food is requested.

━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESPONSE STYLE REQUIREMENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━

All responses must:

• Sound human and natural.
• Be suitable for text-to-speech.
• Avoid robotic formatting.
• Avoid technical tone.
• Start with a warm acknowledgment when appropriate.
• End with a gentle, friendly follow-up question when helpful.
• Be clear and concise.

Imagine you are speaking directly to a guest sitting at a table in the restaurant.

Always sound welcoming.
Always sound confident.
Always sound professional.
Always sound human.

━━━━━━━━━━━━━━━━━━━━━━━━━━━

Current Menu Context:
{context}""".replace('{context}', context)
        
        # Add welcome message section if this is a new session
        welcome_section = ""
        if is_new_session:
            welcome_section = f"""

━━━━━━━━━━━━━━━━━━━━━━━━━━━
WELCOME MESSAGE TO USE (ONLY FOR FIRST MESSAGE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━

When the user sends their first message (greeting, "who are you", or any query), respond with this exact welcome message:

{self._get_welcome_message()}

CRITICAL: Only show this welcome message ONCE at the very beginning of a new conversation. After showing it, continue normally and NEVER repeat it again in the same session.

━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        
        # Inject static restaurant information (about.txt) into the system prompt
        restaurant_info_section = self._restaurant_info_section()
        
        # Combine all parts
        final_prompt = base_prompt + welcome_section + restaurant_info_section
        
        return final_prompt
    
    def generate_response_stream(
        self,
        query: str,
        context: str,
        conversation_history: Optional[List[Dict]] = None
    ):
        """Generate streaming response using LLM"""
        # Build system prompt with welcome message (only for new sessions) and restaurant info
        system_prompt = self._build_system_prompt(context, conversation_history)
        
        # Build messages with conversation history
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history (last few messages for context)
        # Reduced from 6 to 4 for faster processing
        if conversation_history:
            for msg in conversation_history[-4:]:  # Last 4 messages for context
                if msg.get('role') in ['user', 'assistant']:
                    messages.append({
                        "role": msg['role'],
                        "content": msg['content']
                    })
        
        # Add current query with explicit instructions
        user_prompt = f"""
            Customer Question:
            {query}

            Answer using ONLY the provided menu context.
            List all matching items clearly.
            """
        messages.append({"role": "user", "content": user_prompt})
        
        try:
            print(f"🔄 Streaming LLM response ({self.llm_model})...")
            
            # Stream response
            stream = ollama.chat(
                model=self.llm_model,
                messages=messages,
                options={
                    "num_predict": 500,
                    "temperature": 0.7,
                    "num_ctx": 2048,
                },
                stream=True  # Enable streaming
            )
            
            for chunk in stream:
                if 'message' in chunk and 'content' in chunk['message']:
                    content = chunk['message']['content']
                    if content:
                        yield content
                        
        except Exception as e:
            print(f"❌ LLM streaming error: {str(e)}")
            yield f"\n\n[Error: {str(e)}]"
    
    def generate_response(
        self,
        query: str,
        context: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> str:
        """Generate response using LLM with context"""
        
        # Build system prompt with welcome message (only for new sessions) and restaurant info
        system_prompt = self._build_system_prompt(context, conversation_history)
        
        # Build messages with conversation history
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history (last few messages for context)
        if conversation_history:
            for msg in conversation_history[-6:]:  # Last 6 messages for context
                if msg.get('role') in ['user', 'assistant']:
                    messages.append({
                        "role": msg['role'],
                        "content": msg['content']
                    })
        
        # Add current query with explicit instructions
        user_prompt = f"""Query: {query}

IMPORTANT INSTRUCTIONS:
1. Mention ALL items from the context that match this query - do not skip any relevant items
2. If an item doesn't match the query (e.g., savory dishes for "sweet" query), do NOT mention it
3. Number each item clearly (1., 2., 3., etc.)
4. Include item name, section, price (if available), and relevant tags for EACH item
5. Be specific and use exact item names from the context

Provide a helpful response that addresses the query completely."""
        messages.append({"role": "user", "content": user_prompt})
        
        try:
            print(f"🔄 Calling LLM ({self.llm_model})...")
            print(f"   System prompt length: {len(system_prompt)} chars")
            print(f"   Conversation history: {len(conversation_history) if conversation_history else 0} messages")
            
            response = ollama.chat(
                model=self.llm_model,
                messages=messages,
                options={
                   "num_predict": 250,
                    "temperature": 0.2,
                    "top_p": 0.9,
                    "num_ctx": 2048,
                },
                stream=False
            )
            
            print(f"✅ LLM response received")
            result = response['message']['content']
            if not result or len(result.strip()) == 0:
                return "I apologize, but I couldn't generate a response. Please try rephrasing your query."
            return result
        except Exception as e:
            print(f"❌ LLM error: {str(e)}")
            import traceback
            traceback.print_exc()
            return f"I apologize, but I encountered an error: {str(e)}"
    
    def filter_by_relevance(self, query: str, items: List[Dict]) -> List[Dict]:
        """Filter items by keyword relevance to query"""
        if not items:
            return items
        
        # Extract keywords from query (lowercase for matching)
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        # Common query patterns
        sweet_keywords = {'sweet', 'dessert', 'sugar', 'candy', 'honey'}
        savory_keywords = {'spicy', 'savory', 'salty', 'main', 'course', 'curry', 'masala'}
        
        # Check if query is about sweet items
        is_sweet_query = any(word in query_words for word in sweet_keywords)
        is_savory_query = any(word in query_words for word in savory_keywords)
        
        filtered_items = []
        for item in items:
            metadata = item.get('metadata', {})
            item_name = metadata.get('item_name', '').lower()
            tags = metadata.get('tags', '').lower()
            section = metadata.get('section', '').lower()
            
            # Check if item matches query keywords
            item_text = f"{item_name} {tags} {section}"
            
            # For sweet queries, filter out savory items
            if is_sweet_query:
                # Check if item is actually sweet
                item_is_sweet = any(word in item_text for word in ['sweet', 'dessert', 'lassi', 'juice', 'shake', 'ice cream', 'cake'])
                item_is_savory = any(word in item_text for word in ['paneer', 'chicken', 'mutton', 'curry', 'masala', 'chilly', 'pepper', 'dry'])
                
                if item_is_savory and not item_is_sweet:
                    print(f"   ⚠️  Filtering out non-sweet item: {metadata.get('item_name')}")
                    continue
            
            # For savory queries, filter out sweet items
            if is_savory_query and not is_sweet_query:
                item_is_sweet = any(word in item_text for word in ['sweet', 'dessert', 'lassi', 'juice', 'shake'])
                if item_is_sweet:
                    print(f"   ⚠️  Filtering out sweet item: {metadata.get('item_name')}")
                    continue
            
            # If we've already filtered by sweet/savory, add the item
            # Otherwise check if item matches query keywords
            if is_sweet_query or is_savory_query:
                # Already handled above, add item if it passed sweet/savory filter
                filtered_items.append(item)
            else:
                # For general queries, check if item matches any query word
                matches_query = any(word in item_text for word in query_words if len(word) > 2)
                if matches_query or len(query_words) == 0:
                    filtered_items.append(item)
        
        # If filtering removed all items, return original (better than nothing)
        if not filtered_items and items:
            print(f"   ⚠️  Relevance filtering removed all items, using original results")
            return items
        
        return filtered_items
    
    def is_menu_query(self, query: str) -> bool:
        """
        Detect if query is about menu items (food, dishes, prices) vs identity/about/restaurant info.
        Returns True if menu query, False if identity/about query.
        """
        query_lower = query.lower().strip()
        
        # Identity/about patterns (non-menu queries)
        identity_patterns = [
            'who are you', 'what are you', 'who is chikku', 'what is chikku',
            'tell me about', 'about saigon', 'about restaurant', 'about the restaurant',
            'where are you', 'location', 'address', 'located',
            'hours', 'timings', 'opening', 'close', 'when are you open',
            'phone', 'contact', 'email', 'call',
            'reservation', 'reserve', 'booking', 'book a table',
            'hello', 'hi', 'hey', 'greetings', 'namaste',
            'thank you', 'thanks', 'bye', 'goodbye'
        ]
        
        # Check if query matches identity patterns
        for pattern in identity_patterns:
            if pattern in query_lower:
                print(f"🔍 Detected non-menu query (identity/about): '{query}'")
                return False
        
        # Menu-related keywords (food, dishes, prices)
        menu_keywords = [
            'menu', 'dish', 'food', 'item', 'price', 'cost',
            'biryani', 'dosa', 'curry', 'naan', 'tandoori', 'paneer',
            'vegetarian', 'non-vegetarian', 'vegan', 'spicy', 'mild',
            'starter', 'main', 'dessert', 'drink', 'beverage',
            'breakfast', 'lunch', 'dinner', 'appetizer',
            'recommend', 'suggest', 'option', 'available', 'have'
        ]
        
        # If query contains menu keywords, it's likely a menu query
        has_menu_keywords = any(keyword in query_lower for keyword in menu_keywords)
        
        if has_menu_keywords:
            print(f"🔍 Detected menu query: '{query}'")
            return True
        
        # Default: if unclear, assume menu query (backward compatibility)
        print(f"🔍 Unclear intent, defaulting to menu query: '{query}'")
        return True
    
    def answer_about_or_identity(self, query: str, conversation_history: Optional[List[Dict]] = None) -> str:
        """
        Generate response for identity/about queries without menu retrieval.
        Uses deterministic welcome message for identity queries to prevent LLM hallucinations.
        """
        query_lower = query.lower().strip()
        is_new_session = self._is_new_session(conversation_history)
        
        # Check if it's a greeting/identity query
        is_greeting = any(phrase in query_lower for phrase in [
            'who are you', 'what are you', 'who is chikku', 'what is chikku',
            'hello', 'hi', 'hey', 'namaste', 'greetings'
        ])
        
        # Check if it's an "about" query
        is_about_query = any(phrase in query_lower for phrase in [
            'tell me about', 'about saigon', 'about restaurant', 'about the restaurant'
        ])
        
        # DETERMINISTIC: For identity/greeting queries, return welcome message directly
        # This prevents LLM from hallucinating ChatGPT responses
        if is_greeting:
            if is_new_session:
                print("✅ Returning welcome message (deterministic, new session)")
                return self._get_welcome_message()
            else:
                # Not new session, but still identity query - return simple identity response
                print("✅ Returning identity response (deterministic)")
                return "I'm Chikku, your personal food companion, flavor guide, and menu expert at Saigon Indian Restaurant. I'm here to help you discover the perfect dish! What are you craving today? 😊"
        
        # For "about" queries, use LLM with restaurant info but with very strict prompt
        if is_about_query and self.restaurant_info:
            print("📋 Generating about response using restaurant info...")
            context = f"RESTAURANT INFORMATION:\n{self.restaurant_info}"
            system_prompt = self._build_system_prompt(context, conversation_history)
            
            # Build messages with VERY STRICT instructions
            messages = [{"role": "system", "content": system_prompt}]
            
            # Add conversation history
            if conversation_history:
                for msg in conversation_history[-4:]:
                    if msg.get('role') in ['user', 'assistant']:
                        messages.append({
                            "role": msg['role'],
                            "content": msg['content']
                        })
            
            # Add user query with STRICT instructions
            user_prompt = f"""Query: {query}

CRITICAL INSTRUCTIONS:
- You are Chikku, a real hospitality assistant at Saigon Indian Restaurant.
- You are NOT an AI model, NOT ChatGPT, NOT a language model.
- Answer using ONLY the restaurant information provided below.
- Sound warm, human, and professional.
- NEVER mention AI, ChatGPT, models, or technology.

Restaurant Information:
{self.restaurant_info}

Now answer the query naturally as Chikku."""
            
            messages.append({"role": "user", "content": user_prompt})
            
            try:
                print(f"🔄 Generating about response ({self.llm_model})...")
                response = ollama.chat(
                    model=self.llm_model,
                    messages=messages,
                    options={
                        "num_predict": 300,
                        "temperature": 0.3,  # Lower temperature for more deterministic responses
                        "top_p": 0.9,
                        "num_ctx": 2048,
                    },
                    stream=False
                )
                
                result = response['message']['content'].strip()
                
                # Safety check: if response contains AI disclaimers, use fallback
                ai_keywords = ['chatgpt', 'ai model', 'language model', 'artificial intelligence', 'openai', 'google']
                if any(keyword in result.lower() for keyword in ai_keywords):
                    print("⚠️  LLM generated AI disclaimer, using fallback")
                    # Return restaurant info directly formatted nicely
                    return f"""Welcome to Saigon Indian Restaurant! 🇮🇳✨

{self.restaurant_info}

I'm Chikku, your personal food companion here. How can I help you discover our menu today?"""
                
                if result:
                    return result
                else:
                    # Fallback
                    return f"""Welcome to Saigon Indian Restaurant! 🇮🇳✨

{self.restaurant_info}

I'm Chikku, your personal food companion here. How can I help you discover our menu today?"""
            except Exception as e:
                print(f"❌ LLM error in answer_about_or_identity: {str(e)}")
                # Fallback
                return f"""Welcome to Saigon Indian Restaurant! 🇮🇳✨

{self.restaurant_info}

I'm Chikku, your personal food companion here. How can I help you discover our menu today?"""
        
        # Default fallback
        return "I'm Chikku, your personal food companion at Saigon Indian Restaurant. How can I help you today?"
    
    def query(
        self,
        user_query: str,
        top_k: Optional[int] = None,
        rerank_k: Optional[int] = None,
        conversation_history: Optional[List[Dict]] = None
    ) -> Dict:
        """Complete RAG query pipeline"""
        # Use instance defaults or provided values, ensure minimum of 1
        top_k = max(1, top_k) if top_k is not None else self.top_k
        rerank_k = max(1, rerank_k) if rerank_k is not None else self.rerank_k
        
        # Step 0: Check intent - is this a menu query or identity/about query?
        if not self.is_menu_query(user_query):
            print(f"📋 Non-menu query detected, using identity/about handler...")
            response = self.answer_about_or_identity(user_query, conversation_history)
            return {
                'query': user_query,
                'response': response,
                'items': [],
                'retrieved_count': 0
            }
        
        # Step 1: Retrieve (only menu items)
        print(f"📥 Retrieving top {top_k} menu items...")
        print(f"   Collection has {self.collection.count()} total items")
        retrieved = self.retrieve(user_query, top_k=top_k, doc_type="menu")
        print(f"✅ Retrieved {len(retrieved)} items")
        
        if not retrieved:
            print(f"⚠️  No menu items found for query: '{user_query}'")
            # Try without doc_type filter to see if ANY items exist
            print(f"   Testing retrieval without filter...")
            test_retrieved = self.retrieve(user_query, top_k=top_k, doc_type=None)
            print(f"   Without filter: {len(test_retrieved)} items")
            if test_retrieved:
                print(f"   Sample item metadata keys: {list(test_retrieved[0].get('metadata', {}).keys())}")
            return {
                'query': user_query,
                'response': "I couldn't find that in our current menu, but I'd be happy to suggest something similar.",
                'items': [],
                'retrieved_count': 0
            }
        
        # Step 2: Filter by relevance
        print(f"🔍 Filtering items by relevance to query...")
        retrieved_before = len(retrieved)
        retrieved = self.filter_by_relevance(user_query, retrieved)
        print(f"✅ {len(retrieved)} items after relevance filtering (was {retrieved_before})")
        
        # If relevance filtering removed everything, use original results
        if not retrieved and retrieved_before > 0:
            print(f"⚠️  Relevance filtering removed all items, using original {retrieved_before} items")
            retrieved = self.retrieve(user_query, top_k=top_k, doc_type="menu")
            retrieved = [item for item in retrieved if item.get('metadata', {}).get('doc_type') != 'about']
        
        # Step 3: Rerank (optional)
        if self.use_reranking:
            print(f"🔄 Reranking to top {rerank_k} items...")
            retrieved = self.rerank(user_query, retrieved, top_k=rerank_k)
        else:
            retrieved = retrieved[:rerank_k]
            print(f"📊 Using top {len(retrieved)} items (reranking disabled)")
        
        # Step 4: Format context (use all retrieved items)
        print(f"📝 Formatting context for {len(retrieved)} items...")
        context = self.format_context(retrieved)
        
        # Step 5: Generate response with improved prompt
        print(f"🤖 Generating response...")
        response = self.generate_response(user_query, context, conversation_history)
        print(f"✅ Response generated ({len(response)} chars)")
        
        # Prepare result (include all retrieved items)
        result = {
            'query': user_query,
            'response': response,
            'items': [
                {
                    'name': item['metadata'].get('item_name'),
                    'section': item['metadata'].get('section'),
                    'price': item['metadata'].get('price'),
                    'currency': item['metadata'].get('currency'),
                    'tags': item['metadata'].get('tags', '').split(', ') if item['metadata'].get('tags') else []
                }
                for item in retrieved
            ],
            'retrieved_count': len(retrieved)
        }
        
        return result


def main():
    """Test RAG pipeline"""
    project_root = Path(__file__).parent.parent
    chroma_db_path = project_root / "chroma_db"
    
    # Initialize pipeline
    print("Initializing RAG pipeline...")
    rag = RAGPipeline(
        chroma_db_path=str(chroma_db_path),
        use_reranking=False  # Set to True if reranking installed
    )
    
    # Test with single query first
    print("\n" + "="*60)
    print("Testing RAG Pipeline")
    print("="*60 + "\n")
    
    query = "What vegetarian dosas do you have?"
    print(f"Query: {query}")
    print("-" * 60)
    
    try:
        result = rag.query(query, top_k=10, rerank_k=5)
        
        print(f"\nResponse:\n{result['response']}")
        print(f"\nRetrieved {result['retrieved_count']} items")
        if result['items']:
            print("\nTop items:")
            for item in result['items']:
                price_str = f"{item['price']} {item['currency']}" if item.get('price') else "N/A"
                print(f"  - {item['name']} ({item['section']}) - {price_str}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*60)


if __name__ == "__main__":
    main()
