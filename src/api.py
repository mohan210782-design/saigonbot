"""
FastAPI server for Hotel Saigon Chatbot
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from pathlib import Path
import uvicorn
import sys
import os
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("saigonbot.api")

# Add src to path
src_path = Path(__file__).parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from rag import RAGPipeline
from chat import conversation_manager


# Request/Response models
class QueryRequest(BaseModel):
    query: str
    conversation_id: Optional[str] = None  # For conversational context
    top_k: Optional[int] = None  # Uses env var if not provided
    rerank_k: Optional[int] = None  # Uses env var if not provided


class ChatStreamRequest(BaseModel):
    query: str
    conversation_id: Optional[str] = None
    top_k: Optional[int] = None
    rerank_k: Optional[int] = None


class StopRequest(BaseModel):
    conversation_id: str


class MenuItem(BaseModel):
    name: Optional[str] = None
    section: Optional[str] = None
    price: Optional[str] = None
    currency: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


def _none_if_blank(value: Optional[str]) -> Optional[str]:
    """Convert empty/blank strings to None for cleaner API responses."""
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    stripped = value.strip()
    return stripped if stripped else None


class QueryResponse(BaseModel):
    query: str
    response: str
    items: List[MenuItem]
    retrieved_count: int


class HealthResponse(BaseModel):
    status: str
    message: str
    collection_count: Optional[int] = None


# Initialize FastAPI app
app = FastAPI(
    title="Hotel Saigon Chatbot API",
    description="RAG-based chatbot for Hotel Saigon menu queries",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize RAG pipeline (lazy loading)
rag_pipeline: Optional[RAGPipeline] = None
executor = ThreadPoolExecutor(max_workers=2)

# Pre-warm model on startup (optional - uncomment to enable)
# def prewarm_model():
#     """Pre-warm the LLM model to avoid first-request delay"""
#     try:
#         pipeline = get_rag_pipeline()
#         # Send a dummy query to load model into memory
#         pipeline.generate_response("test", "test context")
#         print("✅ Model pre-warmed")
#     except Exception as e:
#         print(f"⚠️  Model pre-warm failed: {e}")


def get_rag_pipeline() -> RAGPipeline:
    """Get or initialize RAG pipeline"""
    global rag_pipeline
    if rag_pipeline is None:
        project_root = Path(__file__).parent.parent
        chroma_db_path = project_root / "chroma_db"
        
        rag_pipeline = RAGPipeline(
            chroma_db_path=str(chroma_db_path),
            use_reranking=False
        )
    return rag_pipeline


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint"""
    return {
        "message": "Hotel Saigon Chatbot API",
        "version": "1.0.0",
        "endpoints": {
            "query": "/query",
            "chat_stream": "/chat/stream",
            "chat_text": "/chat/text",
            "conversation_new": "/conversation/new",
            "health": "/health",
            "docs": "/docs"
        }
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint"""
    try:
        pipeline = get_rag_pipeline()
        collection_count = pipeline.collection.count()
        
        return HealthResponse(
            status="healthy",
            message="API is running",
            collection_count=collection_count
        )
    except Exception as e:
        return HealthResponse(
            status="unhealthy",
            message=f"Error: {str(e)}"
        )


@app.post("/query", response_model=QueryResponse, tags=["Chat"])
async def query_menu(request: QueryRequest):
    """
    Query the menu using RAG pipeline
    
    - **query**: User's question about the menu
    - **top_k**: Number of items to retrieve (uses TOP_K env var if not provided, default: 10)
    - **rerank_k**: Number of items after reranking (uses RERANK_K env var if not provided, default: 5)
    """
    try:
        logger.info(
            "POST /query query=%r conversation_id=%s top_k=%s rerank_k=%s",
            request.query,
            request.conversation_id,
            request.top_k,
            request.rerank_k,
        )
        # Validate query
        if not request.query or not request.query.strip():
            raise HTTPException(
                status_code=400,
                detail="Query cannot be empty"
            )
        
        # Get RAG pipeline
        pipeline = get_rag_pipeline()
        
        # Validate and set top_k/rerank_k (ensure they're at least 1)
        top_k = request.top_k if request.top_k is not None and request.top_k > 0 else None
        rerank_k = request.rerank_k if request.rerank_k is not None and request.rerank_k > 0 else None
        
        # Get conversation history if conversation_id provided
        conversation_history = None
        if request.conversation_id:
            conversation_history = conversation_manager.get_history(request.conversation_id)
        
        # Process query in thread pool to avoid blocking event loop
        # This allows FastAPI to handle other requests while processing
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                executor,
                pipeline.query,
                request.query,
                top_k,
                rerank_k,
                conversation_history
            )
        except Exception:
            logger.exception("pipeline.query failed for /query query=%r", request.query)
            raise
        
        # Save conversation history
        if request.conversation_id:
            conversation_manager.add_message(request.conversation_id, "user", request.query)
            conversation_manager.add_message(request.conversation_id, "assistant", result['response'])
        
        # Convert items to response model
        menu_items: List[MenuItem] = []
        for idx, item in enumerate(result.get('items', [])):
            try:
                if not isinstance(item, dict):
                    logger.warning("Skipping non-dict item at idx=%s: %r", idx, item)
                    continue
                raw_price = item.get('price')
                price_str = None if raw_price in (None, "") else str(raw_price)
                menu_items.append(
                    MenuItem(
                        name=_none_if_blank(item.get('name')),
                        section=_none_if_blank(item.get('section')),
                        price=price_str,
                        currency=_none_if_blank(item.get('currency')),
                        tags=item.get('tags') or []
                    )
                )
            except Exception:
                logger.exception("Failed to build MenuItem at idx=%s item=%r", idx, item)
                # skip bad item rather than failing whole request
                continue
        
        return QueryResponse(
            query=result['query'],
            response=result['response'],
            items=menu_items,
            retrieved_count=result['retrieved_count']
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unhandled error in /query")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@app.post("/chat/stream", tags=["Chat"])
async def chat_stream(request: ChatStreamRequest):
    """
    Streaming chat endpoint with conversation history
    
    Returns Server-Sent Events (SSE) stream of tokens
    """
    try:
        logger.info(
            "POST /chat/stream query=%r conversation_id=%s top_k=%s rerank_k=%s",
            request.query,
            request.conversation_id,
            request.top_k,
            request.rerank_k,
        )
        # Validate query
        if not request.query or not request.query.strip():
            raise HTTPException(status_code=400, detail="Query cannot be empty")
        
        # Get or create conversation
        conv_id = request.conversation_id
        if not conv_id:
            conv_id = conversation_manager.create_conversation()
        
        # Get conversation history
        conversation_history = conversation_manager.get_history(conv_id)
        
        # Add user message to history
        conversation_manager.add_message(conv_id, "user", request.query)
        
        # Get RAG pipeline
        pipeline = get_rag_pipeline()
        
        # Validate and set top_k/rerank_k
        top_k = request.top_k if request.top_k is not None and request.top_k > 0 else None
        rerank_k = request.rerank_k if request.rerank_k is not None and request.rerank_k > 0 else None
        
        async def generate_stream():
            """Async generator for streaming response"""
            try:
                # Check if this is a menu query
                loop = asyncio.get_event_loop()
                is_menu = await loop.run_in_executor(
                    executor,
                    pipeline.is_menu_query,
                    request.query
                )
                
                context = ""
                retrieved = []
                
                if is_menu:
                    # Retrieve items for menu queries
                    retrieved = await loop.run_in_executor(
                        executor,
                        pipeline.retrieve,
                        request.query,
                        top_k or pipeline.top_k,
                        {"doc_type": "menu"},
                    )
                    
                    if retrieved:
                        # Rerank if needed
                        if pipeline.use_reranking:
                            retrieved = await loop.run_in_executor(
                                executor,
                                pipeline.rerank,
                                request.query,
                                retrieved,
                                rerank_k or pipeline.rerank_k
                            )
                        else:
                            retrieved = retrieved[:rerank_k or pipeline.rerank_k]
                        
                        # Format context
                        context = pipeline.format_context(retrieved)
                        
                        # Send items info
                        items_data = []
                        for idx, item in enumerate(retrieved):
                            try:
                                meta = item.get('metadata', {}) if isinstance(item, dict) else {}
                                raw_price = meta.get('price')
                                items_data.append(
                                    {
                                        'name': _none_if_blank(meta.get('item_name')),
                                        'section': _none_if_blank(meta.get('section')),
                                        'price': None if raw_price in (None, "") else str(raw_price),
                                        'currency': _none_if_blank(meta.get('currency')),
                                    }
                                )
                            except Exception:
                                logger.exception("Failed to format stream item idx=%s item=%r", idx, item)
                                continue
                        yield f"data: {json.dumps({'type': 'items', 'items': items_data, 'count': len(items_data)})}\n\n"
                    else:
                        # No items found for menu query
                        yield f"data: {json.dumps({'type': 'items', 'items': [], 'count': 0})}\n\n"
                else:
                    # Non-menu query - send empty items
                    yield f"data: {json.dumps({'type': 'items', 'items': [], 'count': 0})}\n\n"
                
                # Stream LLM response
                full_response = ""
                token_count = 0
                for chunk in pipeline.generate_response_stream(request.query, context, conversation_history):
                    full_response += chunk
                    token_count += 1
                    
                    # Send token for real-time display
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
                    
                    # Send accumulated full response every 10 tokens (for TTS)
                    if token_count % 10 == 0:
                        yield f"data: {json.dumps({'type': 'text', 'content': full_response})}\n\n"
                
                # Send final complete response string (for TTS)
                yield f"data: {json.dumps({'type': 'text', 'content': full_response})}\n\n"
                
                # Send completion with full response
                yield f"data: {json.dumps({'type': 'done', 'conversation_id': conv_id, 'full_response': full_response})}\n\n"
                
                # Save assistant response to history
                conversation_manager.add_message(conv_id, "assistant", full_response)
                
            except Exception as e:
                logger.exception("Streaming generator failed conv_id=%s query=%r", conv_id, request.query)
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
        
        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unhandled error in /chat/stream")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/chat/text", response_model=QueryResponse, tags=["Chat"])
async def chat_text(request: ChatStreamRequest):
    """
    Non-streaming chat endpoint with conversation history
    
    Returns complete response in one request (for desktop apps like Chikku)
    
    - **query**: User's question about the menu
    - **conversation_id**: Optional conversation ID for context
    - **top_k**: Number of items to retrieve (uses TOP_K env var if not provided)
    - **rerank_k**: Number of items after reranking (uses RERANK_K env var if not provided)
    """
    try:
        logger.info(
            "POST /chat/text query=%r conversation_id=%s top_k=%s rerank_k=%s",
            request.query,
            request.conversation_id,
            request.top_k,
            request.rerank_k,
        )
        # Validate query
        if not request.query or not request.query.strip():
            raise HTTPException(
                status_code=400,
                detail="Query cannot be empty"
            )
        
        # Get RAG pipeline
        pipeline = get_rag_pipeline()
        
        # Validate and set top_k/rerank_k (ensure they're at least 1)
        top_k = request.top_k if request.top_k is not None and request.top_k > 0 else None
        rerank_k = request.rerank_k if request.rerank_k is not None and request.rerank_k > 0 else None
        
        # Get or create conversation
        conv_id = request.conversation_id
        if not conv_id:
            conv_id = conversation_manager.create_conversation()
        
        # Get conversation history
        conversation_history = conversation_manager.get_history(conv_id)
        
        # Process query in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                executor,
                pipeline.query,
                request.query,
                top_k,
                rerank_k,
                conversation_history
            )
        except Exception:
            logger.exception("pipeline.query failed for /chat/text query=%r", request.query)
            raise
        
        # Save conversation history
        conversation_manager.add_message(conv_id, "user", request.query)
        conversation_manager.add_message(conv_id, "assistant", result['response'])
        
        # Convert items to response model
        menu_items: List[MenuItem] = []
        for idx, item in enumerate(result.get('items', [])):
            try:
                if not isinstance(item, dict):
                    logger.warning("Skipping non-dict item at idx=%s: %r", idx, item)
                    continue
                raw_price = item.get('price')
                price_str = None if raw_price in (None, "") else str(raw_price)
                menu_items.append(
                    MenuItem(
                        name=_none_if_blank(item.get('name')),
                        section=_none_if_blank(item.get('section')),
                        price=price_str,
                        currency=_none_if_blank(item.get('currency')),
                        tags=item.get('tags') or []
                    )
                )
            except Exception:
                logger.exception("Failed to build MenuItem at idx=%s item=%r", idx, item)
                continue
        
        # Return response
        return QueryResponse(
            query=result['query'],
            response=result['response'],
            items=menu_items,
            retrieved_count=result['retrieved_count']
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unhandled error in /chat/text")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@app.post("/chat/stop", tags=["Chat"])
async def stop_chat(request: StopRequest):
    """Stop ongoing chat generation (placeholder - actual stop requires connection management)"""
    # Note: Actual stop requires tracking active connections
    # This is a placeholder for future implementation
    return {"status": "acknowledged", "message": "Stop request received"}


@app.post("/conversation/new", tags=["Chat"])
async def create_conversation():
    """Create a new conversation"""
    conv_id = conversation_manager.create_conversation()
    return {"conversation_id": conv_id}


@app.get("/conversation/{conv_id}/history", tags=["Chat"])
async def get_conversation_history(conv_id: str):
    """Get conversation history"""
    history = conversation_manager.get_history(conv_id)
    return {"conversation_id": conv_id, "history": history}


@app.delete("/conversation/{conv_id}", tags=["Chat"])
async def clear_conversation(conv_id: str):
    """Clear conversation history"""
    conversation_manager.clear_history(conv_id)
    return {"status": "cleared", "conversation_id": conv_id}


@app.get("/stats", tags=["Stats"])
async def get_stats():
    """Get statistics about the menu"""
    try:
        pipeline = get_rag_pipeline()
        collection_count = pipeline.collection.count()
        
        return {
            "total_items": collection_count,
            "embedding_model": pipeline.embedding_model,
            "llm_model": pipeline.llm_model,
            "reranking_enabled": pipeline.use_reranking
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting stats: {str(e)}"
        )


def main():
    """Run the API server"""
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )


if __name__ == "__main__":
    main()
