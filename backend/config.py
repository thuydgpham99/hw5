"""Shared configuration for the Campus Customs agent team.

One place for the model, the Portkey gateway, the paths, and the limits that keep a
multi-agent run from burning tokens.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent
PROMPTS_DIR = BACKEND_DIR / "prompts"

OUTPUT_DIR = REPO_ROOT / "output"
AUDIT_PATH = OUTPUT_DIR / "audit_trail.json"

ORIGINAL_DB = REPO_ROOT / "data" / "campus_customs.db"
WORKING_DB = REPO_ROOT / "data" / "campus_customs_new.db"
MCP_CONFIG_PATH = REPO_ROOT / ".mcp.json"

# The repo's own .env first, then the course-root .env so one Portkey key serves every
# assignment. Neither file is committed.
load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT.parent / ".env")

# ---------------------------------------------------------------------------------------
# Model: gpt-6-luna through Portkey, for every agent, with no way to swap it from the env.
# PORTKEY_MODEL is deliberately NOT read -- a stale value in a shared .env must not be able
# to put a different model into this run.
# ---------------------------------------------------------------------------------------
MODEL_NAME = "gpt-6-luna"

PORTKEY_BASE_URL = os.environ.get("PORTKEY_BASE_URL", "https://api.portkey.ai/v1")
PORTKEY_API_KEY = os.environ.get("PORTKEY_API_KEY")

if os.environ.get("PORTKEY_MODEL") and os.environ["PORTKEY_MODEL"] != MODEL_NAME:
    print(
        f"[config] Ignoring PORTKEY_MODEL={os.environ['PORTKEY_MODEL']!r}; "
        f"this project is pinned to {MODEL_NAME!r}.",
        file=sys.stderr,
    )


# gpt-6-luna rejects function tools on /v1/chat/completions unless reasoning is off, and it
# ignores temperature while reasoning is on. Every agent here is a tool user, so reasoning
# stays off -- which also keeps the token bill down on a five-agent team.
MODEL_SETTINGS = OpenAIChatModelSettings(openai_reasoning_effort="none", temperature=0.2)


def build_model() -> OpenAIChatModel:
    """The one model every agent on the team uses: gpt-6-luna over the Portkey gateway."""
    if not PORTKEY_API_KEY:
        raise RuntimeError(
            "PORTKEY_API_KEY is not set. Copy .env.example to .env and put your key in it."
        )
    # Portkey speaks the OpenAI wire format, so the OpenAI client works unchanged -- only
    # the base URL differs.
    return OpenAIChatModel(
        MODEL_NAME,
        provider=OpenAIProvider(base_url=PORTKEY_BASE_URL, api_key=PORTKEY_API_KEY),
        settings=MODEL_SETTINGS,
    )


# ---------------------------------------------------------------------------------------
# Limits. A team where everyone can call everyone can spiral; these are the brakes.
# ---------------------------------------------------------------------------------------

# How many agents deep a chain of delegations may go. Boss -> specialist -> specialist
# is depth 2; anything past that has to be answered, not forwarded again.
MAX_DELEGATION_DEPTH = 2

# How many teammates one agent may consult while handling a single ticket.
MAX_DELEGATIONS_PER_AGENT = 3

# Budget for one whole ticket, shared across the boss and every agent it delegates to.
TICKET_USAGE_LIMITS = UsageLimits(
    request_limit=40,
    tool_calls_limit=60,
    total_tokens_limit=180_000,
)

# Who the dashboard records as the approving human when nobody is named.
DEFAULT_APPROVER = "shop owner"
