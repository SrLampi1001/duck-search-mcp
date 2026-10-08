"""MCP prompts registered on the FastMCP instance.

Per the project README: include reusable prompts that make sure any agent
querying via the MCP gets the most from each search. `research_entity` is
the v0.1 prompt — it steers the model toward canonical topic names and the
empty-result fallback described in SPECS §3.
"""
from __future__ import annotations

from fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    @mcp.prompt(
        name="research_entity",
        description=(
            "Plan a web_search call for an entity-shaped topic (person, place, "
            "product, standard, programming language, calculation)."
        ),
    )
    def research_entity(topic: str) -> str:
        """Generate a user message that sets up a single web_search call."""
        return (
            f"Research the topic '{topic}'.\n"
            f"1. Use the web_search tool with a canonical topic name "
            f"(e.g. 'Rust programming language', NOT 'how do I write async code in Rust'). "
            f"Pass count=5.\n"
            f"2. If the result is empty, rephrase once as a canonical topic name and try again.\n"
            f"3. If still empty, fall back to your own knowledge and clearly state that the "
            f"search returned no results."
        )
