"""Wiki research: find a game's wiki, look pages up, and turn them into sanitized cards.

Wiki text is untrusted data: sanitize it before display and never treat it as instructions.
"""

from brain.research.discovery import WikiSite, discover_wiki
from brain.research.models import WikiCard
from brain.research.service import WikiResearch, card_message
from brain.research.websearch import ExaSearch, WebSearch

__all__ = [
    "ExaSearch",
    "WebSearch",
    "WikiCard",
    "WikiResearch",
    "WikiSite",
    "card_message",
    "discover_wiki",
]
