# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0
# as shown at https://oss.oracle.com/licenses/upl/.
"""LangChain agent wiring — ChatOllama + the four retrieval tools.

Public surface:
    diagnose(query: str) -> dict
        Run the agent end-to-end and return a structured result the API/UI
        can render: final answer, ordered list of tool calls, tool results.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_ollama import ChatOllama

from copilot.agent.tools import ALL_TOOLS

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"

SYSTEM_PROMPT = """\
You are an AI on-call assistant for a software engineering team. The user
will paste an alert or describe a live production symptom. Your job is to
ground your answer in the team's incident history and runbooks, not in
general knowledge.

You have four tools. Use them like this:

1. If the user names a specific service, region, or category, use
   `find_similar_incidents_filtered` with those filters. Otherwise use
   `find_similar_incidents` to scan all history.
2. After you find a likely-similar past incident, call
   `get_runbooks_for_incident` with that incident_id to retrieve the
   actual playbook the team used last time.
3. If the user asks who to page or who owns the service, call
   `get_service_owner`.
4. Combine the retrieved facts into a short, actionable answer:
   - 1 sentence on the most likely cause (cite the incident_id).
   - The 2–4 concrete next steps from the runbook(s).
   - Who to page (team + on-call handle), if applicable.

Cite incident_ids and runbook titles in your final answer. If a tool
returns no results, say so explicitly — do NOT invent incidents.
"""


@lru_cache(maxsize=1)
def _model() -> ChatOllama:
    return ChatOllama(
        model=os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
        base_url=os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_URL),
        temperature=0.0,
    )


@lru_cache(maxsize=1)
def _agent():
    return create_agent(
        model=_model(),
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
    )


def _flatten(messages: list[Any]) -> dict:
    """Pull final answer + tool-call trace out of the agent's message log."""
    tool_calls: list[dict] = []
    tool_results: list[dict] = []
    final_answer = ""
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in getattr(m, "tool_calls", []) or []:
                tool_calls.append({"name": tc.get("name"), "args": tc.get("args")})
            if m.content and not getattr(m, "tool_calls", None):
                final_answer = m.content if isinstance(m.content, str) else str(m.content)
        elif isinstance(m, ToolMessage):
            tool_results.append({"name": m.name, "result": m.content})
    return {
        "answer": final_answer,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
    }


def diagnose(query: str) -> dict:
    """Run the agent on a free-text incident description, return structured trace + answer."""
    result = _agent().invoke({"messages": [HumanMessage(content=query)]})
    return _flatten(result.get("messages", []))


__all__ = ["diagnose", "SYSTEM_PROMPT"]
