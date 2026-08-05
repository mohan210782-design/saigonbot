"""
LLM Provider abstraction layer.

Embeddings:  always Ollama (mxbai-embed-large) — keeps ChromaDB index stable.
Generation:  switch via LLM_PROVIDER in .env
               LLM_PROVIDER=ollama  → local Ollama model
               LLM_PROVIDER=openai  → OpenAI API
"""
import os
from typing import List, Dict, Iterator, Optional
from dotenv import load_dotenv

load_dotenv()


class LLMProvider:
    """Base interface for LLM providers."""

    llm_model: str
    embedding_model: str

    def embed(self, text: str) -> List[float]:
        raise NotImplementedError

    def chat(self, messages: List[Dict], options: Dict) -> str:
        """Non-streaming generation. options keys: max_tokens, temperature, top_p, num_ctx"""
        raise NotImplementedError

    def stream_chat(self, messages: List[Dict], options: Dict) -> Iterator[str]:
        """Streaming generation — yields text chunks."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Ollama — used for BOTH embeddings and generation
# ---------------------------------------------------------------------------

class OllamaProvider(LLMProvider):
    def __init__(self, llm_model: str, embedding_model: str):
        import ollama as _ollama
        self._ollama = _ollama
        self.llm_model = llm_model
        self.embedding_model = embedding_model

    def _ollama_options(self, options: Dict) -> Dict:
        opts = {
            "num_predict": options.get("max_tokens", 512),
            "temperature": options.get("temperature", 0.7),
            "top_p":       options.get("top_p", 0.9),
            "num_ctx":     options.get("num_ctx", 2048),
        }
        num_gpu_env = os.getenv("OLLAMA_NUM_GPU")
        if num_gpu_env is not None:
            try:
                num_gpu = int(num_gpu_env)
                opts["num_gpu"] = num_gpu
                if num_gpu == 0:
                    print("   ⚙️  Forcing CPU usage (OLLAMA_NUM_GPU=0)")
            except (ValueError, TypeError):
                pass
        return opts

    def embed(self, text: str) -> List[float]:
        response = self._ollama.embeddings(model=self.embedding_model, prompt=text)
        return response["embedding"]

    def chat(self, messages: List[Dict], options: Dict) -> str:
        response = self._ollama.chat(
            model=self.llm_model,
            messages=messages,
            options=self._ollama_options(options),
            stream=False,
        )
        return response["message"]["content"]

    def stream_chat(self, messages: List[Dict], options: Dict) -> Iterator[str]:
        stream = self._ollama.chat(
            model=self.llm_model,
            messages=messages,
            options=self._ollama_options(options),
            stream=True,
        )
        for chunk in stream:
            if "message" in chunk and "content" in chunk["message"]:
                content = chunk["message"]["content"]
                if content:
                    yield content


# ---------------------------------------------------------------------------
# OpenAI — generation only; embeddings are delegated to Ollama
# ---------------------------------------------------------------------------

class OpenAIGenerationProvider(LLMProvider):
    """
    Uses OpenAI for chat/stream_chat.
    Embeddings always go through Ollama so ChromaDB index stays consistent.
    """

    def __init__(self, llm_model: str, embedding_model: str, api_key: str):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key)
        self.llm_model = llm_model
        self.embedding_model = embedding_model  # Ollama model, used by embed()

        # Internal Ollama instance for embeddings only
        import ollama as _ollama
        self._ollama = _ollama

    def embed(self, text: str) -> List[float]:
        """Always uses Ollama — keeps embeddings consistent with ChromaDB index."""
        response = self._ollama.embeddings(model=self.embedding_model, prompt=text)
        return response["embedding"]

    def chat(self, messages: List[Dict], options: Dict) -> str:
        response = self._client.chat.completions.create(
            model=self.llm_model,
            messages=messages,
            max_tokens=options.get("max_tokens", 512),
            temperature=options.get("temperature", 0.7),
            top_p=options.get("top_p", 0.9),
            stream=False,
        )
        return response.choices[0].message.content

    def stream_chat(self, messages: List[Dict], options: Dict) -> Iterator[str]:
        stream = self._client.chat.completions.create(
            model=self.llm_model,
            messages=messages,
            max_tokens=options.get("max_tokens", 512),
            temperature=options.get("temperature", 0.7),
            top_p=options.get("top_p", 0.9),
            stream=True,
        )
        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                yield content


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_provider() -> LLMProvider:
    """
    Returns the configured provider.

    Embeddings always use Ollama (EMBEDDING_MODEL).
    Generation uses LLM_PROVIDER:
      - ollama  → OllamaProvider       (local, default)
      - openai  → OpenAIGenerationProvider (OpenAI chat + Ollama embeddings)
    """
    provider_name   = os.getenv("LLM_PROVIDER", "ollama").lower().strip()
    embedding_model = os.getenv("EMBEDDING_MODEL", "mxbai-embed-large")

    if provider_name == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY is required when LLM_PROVIDER=openai. "
                "Add it to your .env file."
            )
        llm_model = os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini")
        print(f"🤖 Generation: OpenAI ({llm_model})  |  Embeddings: Ollama ({embedding_model})")
        return OpenAIGenerationProvider(
            llm_model=llm_model,
            embedding_model=embedding_model,
            api_key=api_key,
        )

    else:  # default: ollama
        llm_model = os.getenv("LLM_MODEL", "llama3:8b-instruct-q4_0")
        print(f"🤖 Generation: Ollama ({llm_model})  |  Embeddings: Ollama ({embedding_model})")
        return OllamaProvider(llm_model=llm_model, embedding_model=embedding_model)


# ---------------------------------------------------------------------------
# Rewrite provider — for query rewrite / STT correction
# ---------------------------------------------------------------------------
# Voice input is error-prone on proper nouns ("S-Robot" → "EST robot",
# "WatchGuard6S" → "watch guards"). A small fast LOCAL model is ideal for
# this short, latency-sensitive task. This provider is SEPARATE from the
# main generation provider so you can mix e.g. OpenAI generation with a
# local Ollama rewriter (the recommended Voice AI setup).
#
# Config (all optional — falls back gracefully):
#   REWRITE_PROVIDER = ollama | openai   (default: ollama)
#   REWRITE_MODEL    = ollama model tag  (default: llama3.2:3b-instruct)
#   OPENAI_LLM_MODEL = used when REWRITE_PROVIDER=openai
#
# get_rewrite_provider() returns None on any init failure; callers must
# handle None by skipping rewrite (never let rewrite break the pipeline).

_rewrite_provider: Optional[LLMProvider] = None
_rewrite_provider_init_attempted = False


def get_rewrite_provider() -> Optional[LLMProvider]:
    """Return the dedicated rewrite/STT-correction provider, or None.

    Lazily initialized once. If init fails (missing model, no ollama, etc.),
    returns None permanently and logs once — callers fall back to no rewrite.
    """
    global _rewrite_provider, _rewrite_provider_init_attempted
    if _rewrite_provider_init_attempted:
        return _rewrite_provider
    _rewrite_provider_init_attempted = True

    provider_name = os.getenv("REWRITE_PROVIDER", "ollama").lower().strip()
    embedding_model = os.getenv("EMBEDDING_MODEL", "mxbai-embed-large")

    try:
        if provider_name == "openai":
            api_key = os.getenv("OPENAI_API_KEY", "")
            if not api_key:
                print("ℹ️  Rewrite provider: OPENAI_API_KEY missing — rewrite disabled.")
                return None
            model = os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini")
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            _rewrite_provider = _BareChatProvider(client, model)
            print(f"✍️  Rewrite: OpenAI ({model})")
        else:  # ollama (default for Voice AI — fast + local)
            import ollama as _ollama
            model = os.getenv("REWRITE_MODEL", "llama3.2:3b-instruct")
            _rewrite_provider = _BareChatProvider(_ollama, model, backend="ollama")
            print(f"✍️  Rewrite: Ollama ({model})")
    except Exception as e:
        print(f"ℹ️  Rewrite provider unavailable ({e}) — rewrite disabled. "
              f"Pull the model (e.g. `ollama pull llama3.2:3b-instruct`) to enable.")
        _rewrite_provider = None
    return _rewrite_provider


class _BareChatProvider:
    """Minimal chat-only wrapper for the rewrite task.

    Wraps either an OpenAI client or an Ollama module so the rewrite path
    can use a small fast model without pulling in the full LLMProvider
    interface (no embedding support needed here). Exposes .chat(messages,
    options) returning a string.
    """

    def __init__(self, client, model: str, backend: str = "openai"):
        self._client = client
        self.model = model
        self.backend = backend

    def chat(self, messages, options: dict) -> str:
        if self.backend == "ollama":
            opts = {
                "num_predict": options.get("max_tokens", 150),
                "temperature": options.get("temperature", 0.2),
                "top_p": options.get("top_p", 0.9),
                "num_ctx": options.get("num_ctx", 1024),
            }
            num_gpu_env = os.getenv("OLLAMA_NUM_GPU")
            if num_gpu_env is not None:
                try:
                    opts["num_gpu"] = int(num_gpu_env)
                except (ValueError, TypeError):
                    pass
            resp = self._client.chat(
                model=self.model, messages=messages, options=opts, stream=False
            )
            return resp["message"]["content"]
        else:  # openai
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=options.get("max_tokens", 150),
                temperature=options.get("temperature", 0.2),
                top_p=options.get("top_p", 0.9),
                stream=False,
            )
            return resp.choices[0].message.content
