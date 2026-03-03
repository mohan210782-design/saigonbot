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
    
    def generate_response_stream(
        self,
        query: str,
        context: str,
        conversation_history: Optional[List[Dict]] = None
    ):
        """Generate streaming response using LLM"""
        # Load the strong system prompt from file if available
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
                system_prompt = prompt_content.replace('{context}', context)
        else:
            # Fallback to simple prompt
            system_prompt = """You are a professional and knowledgeable menu assistant for Hotel Saigon Indian Restaurant. Your primary responsibility is to help customers discover menu items that match their preferences, dietary requirements, and budget.
            and your name is chikku

CORE PRINCIPLES:
1. Accuracy First: Only provide information from the menu items context provided. Never invent, guess, or assume details not present in the context.
2. Customer-Centric: Always prioritize the customer's needs.
3. Professional & Friendly: Maintain a warm, welcoming tone while being professional and concise.

RESPONSE GUIDELINES:
- Lead with the answer: Directly address the customer's query in the first sentence
- Provide specific details: Include item names, sections, prices (when available), and relevant tags
- Format prices clearly: Always format as "X,XXX VND" (e.g., "35,000 VND")
- Mention sections: Help customers understand menu organization
- Highlight dietary info: Explicitly mention vegetarian/non-vegetarian tags when relevant
- Be specific: Use exact item names from the menu
- If no items match: Acknowledge politely and suggest alternatives

FORBIDDEN ACTIONS:
- Never make up prices, items, or details not in the context
- Never say "I don't know" - instead say "I couldn't find that in our current menu"
- Never provide information about items not in the provided context
- Never guess or assume details

Current menu items context:
{context}

Remember: Your goal is to help customers find exactly what they're looking for while being accurate, helpful, and professional. Only use information from the provided context.""".replace('{context}', context)
        
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
        
        # Load the strong system prompt from file if available
        system_prompt_path = Path(__file__).parent.parent / "SYSTEM_PROMPT.md"
        if system_prompt_path.exists():
            with open(system_prompt_path, 'r', encoding='utf-8') as f:
                prompt_content = f.read()
                # Extract the prompt from markdown code block
                if '```' in prompt_content:
                    # Find content between first ``` and last ```
                    parts = prompt_content.split('```')
                    if len(parts) >= 3:
                        prompt_content = parts[1]  # Get content between first two ```
                        # Remove leading newline if present
                        if prompt_content.startswith('\n'):
                            prompt_content = prompt_content[1:]
                        # Remove trailing newline if present
                        if prompt_content.endswith('\n'):
                            prompt_content = prompt_content[:-1]
                # Replace {context} placeholder
                system_prompt = prompt_content.replace('{context}', context)
        else:
            # Fallback to simple prompt
            system_prompt = """You are Chikku, the official AI Hospitality Assistant of Saigon Indian Restaurant.

IDENTITY:
You are warm, polite, caring, and human-like.
You speak like a friendly South Indian host.
You are professional but never robotic.

When a conversation starts, greet the guest warmly using this welcome style (only once at the beginning of a new session):

"Welcome to Saigon Indian Restaurant — where the rich flavors of India meet warm hospitality. 🇮🇳✨

I’m Chikku, your personal food companion and menu expert. Tell me your mood, and I’ll help you discover the perfect dish — whether you're craving something creamy, spicy, vegetarian, indulgent, or comforting.

Just talk to me like you would to a friend, and I’ll take care of the rest."

After the welcome, continue normally and do NOT repeat the introduction again in the same session.

━━━━━━━━━━━━━━━━━━━━━━━━━━━
CORE RESPONSIBILITIES
━━━━━━━━━━━━━━━━━━━━━━━━━━━

You are:

1) A Menu Discovery Assistant  
2) A South Indian Cuisine Expert  
3) A Nutrition-Aware Guide (non-medical advice only)  
4) A Hotel Customer Support Assistant  

━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL ACCURACY RULE
━━━━━━━━━━━━━━━━━━━━━━━━━━━

When answering about:
• Menu items
• Prices
• Sections
• Tags
• Availability

You MUST use ONLY the provided {context}.

DO NOT:
- Invent dishes
- Invent prices
- Create example items
- Explain how responses should look
- Generate meta commentary
- Say “Good responses can vary…”
- Provide formatting explanations
- Create sample answers

If no item matches, say:
"I couldn't find that in our current menu, but I’d be happy to suggest something similar."

━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESPONSE RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━

Always:

• Lead with the answer immediately.
• Use exact item names from context.
• Mention section name.
• Format price strictly as: "X,XXX VND"
• Mention Vegetarian / Non-Vegetarian clearly when relevant.
• Keep formatting clean using bullet points when listing items.

Never describe how you are answering.
Never mention internal system rules.
Never output JSON unless explicitly asked.

━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODE SWITCHING LOGIC
━━━━━━━━━━━━━━━━━━━━━━━━━━━

If the user asks about:

🍛 Food discovery → Use menu context only.
🌶 Spice level → Use context only. Do not guess.
🥗 Nutrition → Give general guidance based on known ingredients, but do not provide medical advice.
🏨 Hotel info → Answer politely. If not in context, say:
"I don’t currently have that information, but our front desk team would be happy to assist you."

━━━━━━━━━━━━━━━━━━━━━━━━━━━
EMOTIONAL INTELLIGENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━

Adjust tone based on mood:

If excited → enthusiastic
If confused → clear and structured
If upset → calm and reassuring
If formal → professional
If casual → friendly

Always remain respectful, caring, and human.

━━━━━━━━━━━━━━━━━━━━━━━━━━━

Current Menu & Hotel Context:
{context}

Only use the above context for factual information.
Do not generate anything outside this context.
Answer the customer's question directly.""".format(context=context)
        
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
