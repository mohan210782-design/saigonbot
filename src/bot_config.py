"""
Bot Identity Configuration Module
==================================
Centralized configuration for Chikku Robotics chatbot.

Usage:
    from bot_config import get_bot_config
    cfg = get_bot_config()
    print(cfg.bot_name)           # "Chikku"
    print(cfg.collection_name)    # "chikku_robotics"
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Bot identity definition
# ---------------------------------------------------------------------------
@dataclass
class BotIdentity:
    """Holds all identity-specific configuration for the bot."""

    bot_name: str
    company_name: str
    company_tagline: str
    api_title: str
    api_description: str
    api_version: str

    # -- ChromaDB --
    collection_name: str

    # -- file paths (relative to project root) --
    system_prompt_file: str
    about_file: str
    knowledge_base_dirs: List[str]

    # -- error / fallback --
    fallback_phone: str
    fallback_email: str

    # -- context formatting --
    context_formatter: str           # "generic"


# ---------------------------------------------------------------------------
# Chikku Robotics identity (the only identity)
# ---------------------------------------------------------------------------

_ROBOTICS_IDENTITY = BotIdentity(
    bot_name="Chikku",
    company_name="Chikku Robotics",
    company_tagline="Intelligent Robots for a Smarter Future",
    api_title="Chikku Robotics Chatbot API",
    api_description="RAG-based chatbot for Chikku Robotics — AI & Robotics company",
    api_version="1.0.0",
    collection_name="chikku_robotics",
    system_prompt_file="data/system_prompt_robotics.txt",
    about_file="data/processed/about_robotics.txt",
    knowledge_base_dirs=["robotics"],
    fallback_phone="",
    fallback_email="info@chikkurobotics.com",
    context_formatter="generic",
)


# ---------------------------------------------------------------------------
# Singleton config access
# ---------------------------------------------------------------------------

_config: BotIdentity | None = None


def get_bot_config() -> BotIdentity:
    """Return the Chikku Robotics bot configuration."""
    global _config
    if _config is None:
        _config = _ROBOTICS_IDENTITY
    return _config


def get_project_root() -> Path:
    """Return the absolute project root directory."""
    return Path(__file__).parent.parent


def resolve_path(relative_path: str) -> Path:
    """Resolve a path relative to the project root."""
    return get_project_root() / relative_path


def is_robotics() -> bool:
    """Always True — this is a robotics-only codebase."""
    return True
