"""
FastAPI server for Hotel Saigon Chatbot
"""
from fastapi import FastAPI, HTTPException, Request, status
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
import uuid
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Add src to path FIRST so all local imports resolve correctly
src_path = Path(__file__).parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Logging - use structured logging if configured
from logging_config import setup_logging, RequestLogger

log_level = os.getenv("LOG_LEVEL", "INFO")
use_json_logs = os.getenv("USE_JSON_LOGS", "false").lower() == "true"
setup_logging(log_level=log_level, use_json=use_json_logs)

logger = logging.getLogger("saigonbot.api")

from rag import RAGPipeline
from chat import conversation_manager
from errors import handle_error, ValidationError, SystemError
from rate_limit import RATE_LIMIT_ENABLED, get_rate_limiter
from bot_config import get_bot_config


# Request/Response models
class QueryRequest(BaseModel):
    query: str
    conversation_id: Optional[str] = None


class ChatStreamRequest(BaseModel):
    query: str
    conversation_id: Optional[str] = None


class ChatVoiceRequest(BaseModel):
    """Request body for the streaming /chat/voice endpoint.

    Identical to ChatStreamRequest — kept as a distinct type so the voice
    pipeline (which emits filler signals for the frontend TTS) is clearly
    separated from the legacy token-streaming endpoint in the OpenAPI docs.
    """
    query: str
    conversation_id: Optional[str] = None


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
    intent: Optional[Dict] = None  # Intent classification result


class HealthResponse(BaseModel):
    status: str
    message: str
    collection_count: Optional[int] = None


# Initialize FastAPI app
_bot_cfg = get_bot_config()
app = FastAPI(
    title=_bot_cfg.api_title,
    description=_bot_cfg.api_description,
    version=_bot_cfg.api_version
)

# CORS middleware
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
if allowed_origins_env.strip() == "*":
    allow_origins = ["*"]
else:
    allow_origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize RAG pipeline (lazy loading)
rag_pipeline: Optional[RAGPipeline] = None
executor = ThreadPoolExecutor(max_workers=2)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """
    Simple IP-based rate limiting middleware.
    Controlled by RATE_LIMIT_ENABLED and RATE_LIMIT_* env vars.
    """
    if not RATE_LIMIT_ENABLED:
        return await call_next(request)

    # Use client host as key; could be extended with session_id if needed
    client_host = request.client.host if request.client else "unknown"
    limiter = get_rate_limiter()

    if not limiter.check(client_host):
        logger.warning("Rate limit exceeded", extra={"client_host": client_host})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down and try again shortly.",
        )

    return await call_next(request)

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
        )
    return rag_pipeline


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint"""
    cfg = get_bot_config()
    return {
        "message": cfg.api_title,
        "version": cfg.api_version,
        "endpoints": {
            "query": "/query",
            "chat_stream": "/chat/stream",
            "chat_voice": "/chat/voice",
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
    """
    request_id = str(uuid.uuid4())
    with RequestLogger(logger, request_id) as req_logger:
        req_logger.log_request(
            endpoint="/query",
            query=request.query[:100],  # Truncate for logging
            conversation_id=request.conversation_id,
        )

    try:
        # Validate query
        if not request.query or not request.query.strip():
            raise HTTPException(
                status_code=400,
                detail="Query cannot be empty"
            )
        
        # Get RAG pipeline
        pipeline = get_rag_pipeline()
        
        # Get or create conversation using session_id
        session_id = request.conversation_id or str(uuid.uuid4())
        conv_id = conversation_manager.get_or_create_conversation(session_id)
        
        # Get conversation history
        conversation_history = conversation_manager.get_history(conv_id)
        
        # Process query in thread pool to avoid blocking event loop
        # This allows FastAPI to handle other requests while processing
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                executor,
                pipeline.query,
                request.query,
                None,
                None,
                conversation_history
            )
        except Exception as e:
            logger.exception("pipeline.query failed for /query query=%r", request.query)
            # Return user-friendly error response instead of raising
            error_msg = handle_error(e, context={"query": request.query, "endpoint": "/query"})
            # Get intent even for errors
            try:
                from intent_classifier import get_intent_classifier
                classifier = get_intent_classifier()
                intent_result = classifier.classify_intent(request.query)
                intent_dict = intent_result.to_dict()
            except:
                intent_dict = None
            
            return QueryResponse(
                query=request.query,
                response=error_msg,
                items=[],
                retrieved_count=0,
                intent=intent_dict
            )
        
        # Save conversation history with intent information
        intent_info = result.get('intent', {})
        intent_type = intent_info.get('intent_type') if intent_info else None
        
        conversation_manager.add_message(
            conv_id, "user", request.query,
            intent=intent_type,
            metadata={"query": request.query}
        )
        conversation_manager.add_message(
            conv_id, "assistant", result['response'],
            intent=intent_type,
            metadata={
                "retrieved_count": result.get('retrieved_count', 0),
                "items_count": len(result.get('items', []))
            }
        )
        
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
            retrieved_count=result['retrieved_count'],
            intent=result.get('intent')
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
            "POST /chat/stream query=%r conversation_id=%s",
            request.query,
            request.conversation_id,
        )
        # Validate query
        if not request.query or not request.query.strip():
            raise HTTPException(status_code=400, detail="Query cannot be empty")
        
        # Get or create conversation using session_id
        session_id = request.conversation_id or str(uuid.uuid4())
        conv_id = conversation_manager.get_or_create_conversation(session_id)
        
        # Get conversation history
        conversation_history = conversation_manager.get_history(conv_id)
        
        # Add user message to history
        conversation_manager.add_message(conv_id, "user", request.query)
        
        # Get RAG pipeline
        pipeline = get_rag_pipeline()
        
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
                        pipeline.top_k,
                        "menu",
                    )
                    
                    if retrieved:
                        # Rerank if needed
                        if pipeline.use_reranking:
                            retrieved = await loop.run_in_executor(
                                executor,
                                pipeline.rerank,
                                request.query,
                                retrieved,
                                pipeline.rerank_k
                            )
                        else:
                            retrieved = retrieved[:pipeline.rerank_k]
                        
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
                yield f"data: {json.dumps({'type': 'done', 'conversation_id': session_id, 'full_response': full_response})}\n\n"
                
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
    """
    try:
        logger.info(
            "POST /chat/text query=%r conversation_id=%s",
            request.query,
            request.conversation_id,
        )
        # Validate query
        if not request.query or not request.query.strip():
            raise HTTPException(
                status_code=400,
                detail="Query cannot be empty"
            )
        
        # Get RAG pipeline
        pipeline = get_rag_pipeline()
        
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
                None,
                None,
                conversation_history
            )
        except Exception:
            logger.exception("pipeline.query failed for /chat/text query=%r", request.query)
            raise
        
        # Save conversation history with intent information
        intent_info = result.get('intent', {})
        intent_type = intent_info.get('intent_type') if intent_info else None
        
        conversation_manager.add_message(
            conv_id, "user", request.query,
            intent=intent_type,
            metadata={"query": request.query}
        )
        conversation_manager.add_message(
            conv_id, "assistant", result['response'],
            intent=intent_type,
            metadata={
                "retrieved_count": result.get('retrieved_count', 0),
                "items_count": len(result.get('items', []))
            }
        )
        
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
            retrieved_count=result['retrieved_count'],
            intent=result.get('intent')
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unhandled error in /chat/text")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@app.post("/chat/voice", tags=["Chat"])
async def chat_voice(request: ChatVoiceRequest):
    """
    Voice-optimized streaming endpoint for the Chikku desktop client.

    Returns a Server-Sent Events (SSE) stream of pipeline events. Unlike
    /chat/text (one JSON blob at the end), this endpoint emits a **filler
    signal** the instant the FAQ cache MISSES, so the frontend can start
    speaking a filler sentence while the slow hybrid-retrieval + LLM
    steps run (4-6s), then stop the filler and speak the real response.

    Because this uses POST (with a JSON body), the browser EventSource API
    cannot be used (it only supports GET). The frontend must consume the
    stream via fetch() + ReadableStream — see the usage guide.

    Event schema (each line: ``data: {json}\\n\\n``):
      - ``{"type": "filler"}``
            FAQ cache missed. Speak a filler now (frontend owns the text).
      - ``{"type": "response", "query", "response", "items", "retrieved_count", "intent", "source"}``
            Final answer ready. Stop the filler (if any) and speak this.
            ``source`` ∈ deterministic | faq_cache | llm | fallback.
      - ``{"type": "done", "conversation_id", "intent"}``
            Stream complete. Safe to close the connection.
      - ``{"type": "error", "message"}``
            Pipeline failure; the stream ends after this.
    """
    try:
        logger.info(
            "POST /chat/voice query=%r conversation_id=%s",
            request.query,
            request.conversation_id,
        )
        # Validate query
        if not request.query or not request.query.strip():
            raise HTTPException(
                status_code=400,
                detail="Query cannot be empty"
            )

        # Get RAG pipeline
        pipeline = get_rag_pipeline()

        # Get or create conversation
        session_id = request.conversation_id or str(uuid.uuid4())
        conv_id = conversation_manager.get_or_create_conversation(session_id)

        # Get conversation history (read BEFORE adding the new user message,
        # so the pipeline sees prior turns as context — same as /chat/text).
        conversation_history = conversation_manager.get_history(conv_id)

        # Bridge a synchronous generator (query_stream, runs in a worker
        # thread so it doesn't block the event loop) to this async generator.
        # The worker pushes events onto an asyncio queue; we pull them here.
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        SENTINEL = object()  # marks end-of-stream from the worker

        def _run_pipeline():
            """Run query_stream() in a thread, forwarding events to the queue."""
            try:
                for event in pipeline.query_stream(
                    request.query, None, None, conversation_history
                ):
                    asyncio.run_coroutine_threadsafe(queue.put(event), loop).result()
            except Exception as e:
                logger.exception(
                    "query_stream failed conv_id=%s query=%r", conv_id, request.query
                )
                asyncio.run_coroutine_threadsafe(
                    queue.put({"type": "error", "message": str(e)}), loop
                ).result()
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(SENTINEL), loop).result()

        # Launch the worker thread
        loop.run_in_executor(executor, _run_pipeline)

        async def generate_stream():
            """Async generator: pull events from the queue, emit as SSE."""
            saved = False  # only persist history once
            try:
                while True:
                    item = await queue.get()
                    if item is SENTINEL:
                        break

                    # Persist the conversation the first time we see the
                    # final response (so it's saved even if the client later
                    # disconnects). We add the user turn here too, mirroring
                    # /chat/text's ordering.
                    if item.get("type") == "response" and not saved:
                        saved = True
                        intent_info = item.get("intent") or {}
                        intent_type = intent_info.get("intent_type") if intent_info else None
                        conversation_manager.add_message(
                            conv_id, "user", request.query,
                            intent=intent_type,
                            metadata={"query": request.query}
                        )
                        conversation_manager.add_message(
                            conv_id, "assistant", item.get("response", ""),
                            intent=intent_type,
                            metadata={
                                "retrieved_count": item.get("retrieved_count", 0),
                                "source": item.get("source"),
                                "items_count": len(item.get("items", []))
                            }
                        )

                    # The 'done' event carries the conversation_id so the
                    # frontend can continue the same session.
                    if item.get("type") == "done":
                        item = dict(item)
                        item["conversation_id"] = session_id

                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            except asyncio.CancelledError:
                # Client disconnected — let the worker finish on its own.
                raise

        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"  # disable proxy buffering (nginx)
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unhandled error in /chat/voice")
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
    session_id = str(uuid.uuid4())
    conv_id = conversation_manager.create_conversation(session_id=session_id)
    return {"conversation_id": session_id, "internal_id": conv_id}


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
