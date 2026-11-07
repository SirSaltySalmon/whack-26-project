"""WP8: reading the wiki page the player has open, matching it locally, and the tool."""

import ast
import asyncio
import inspect
from collections.abc import Callable
from pathlib import Path

import pytest

import brain.research.open_page as open_page_module
import brain.research.page_match as page_match_module
from brain.events import (
    CardClosedByPlayer,
    CardPageChanged,
    EventBus,
    PageContentReceived,
    PlayerStartedSpeaking,
)
from brain.memory.fts import query_terms
from brain.research.open_page import NOTHING_OPEN, OFF_WIKI, PAGE_LABEL, OpenPage
from brain.research.page_match import match_passages
from brain.tests.agent_rig import rig
from shared.protocol import BrainMessage
from shared.protocol.messages import PageRead

WIKI = "terraria.wiki.gg"
PAGE = f"https://{WIKI}/wiki/Skeletron"
PAGE_TEXT = (
    "Skeletron is a pre-Hardmode boss.\n"
    "\n"
    "Summoning\n"
    "Talk to the Clothier at night and choose Curse to start the fight.\n"
    "Drops\n"
    "It drops the Skeletron Mask and a Book of Skulls.\n"
    "Tips\n"
    "Fight it on a long, flat bridge."
)
VISIBLE_TEXT = "Drops\nIt drops the Skeletron Mask and a Book of Skulls."


class Harness:
    def __init__(self, host: str | None = WIKI, **limits: int) -> None:
        self.bus = EventBus()
        self.sent: list[BrainMessage] = []
        self.page = OpenPage(self.bus, self._send, lambda: host, **limits)
        self.task: asyncio.Task[None] | None = None

    async def _send(self, message: BrainMessage) -> None:
        self.sent.append(message)

    @property
    def reads(self) -> list[PageRead]:
        return [m for m in self.sent if isinstance(m, PageRead)]

    async def __aenter__(self) -> "Harness":
        self.task = asyncio.create_task(self.page.run())
        return self

    async def __aexit__(self, *_: object) -> None:
        assert self.task is not None
        assert not self.task.done(), "OpenPage.run stopped"
        self.task.cancel()

    async def publish(self, event: object) -> None:
        self.bus.publish(event)  # type: ignore[arg-type]
        for _ in range(20):
            await asyncio.sleep(0)

    async def until(self, condition: Callable[[], bool]) -> None:
        # Snapshots are built in a worker thread, so real time has to pass.
        for _ in range(200):
            if condition():
                return
            await asyncio.sleep(0.005)
        raise AssertionError("Condition never became true")

    async def open(self, url: str = PAGE) -> None:
        await self.publish(CardPageChanged(card_id="wiki", url=url, title="Skeletron"))

    async def read_page(self, url: str = PAGE, text: str = PAGE_TEXT) -> None:
        """Starts a turn, then answers the read request the way the overlay would."""
        await self.publish(PlayerStartedSpeaking())
        request = self.reads[-1]
        await self.publish(content(request.request_id, url, text))
        await self.until(lambda: self.page.excerpt_for("drops") is not None)


def content(request_id: str, url: str = PAGE, text: str = PAGE_TEXT) -> PageContentReceived:
    return PageContentReceived(
        request_id=request_id,
        card_id="wiki",
        url=url,
        title="Skeletron - Terraria Wiki",
        text=text,
        visible_text=VISIBLE_TEXT,
    )


# --- Reading only the wiki ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("url", "reads"),
    [
        (PAGE, 1),
        (f"http://{WIKI}/wiki/Eye", 1),
        ("https://wiki.gg/wiki/Skeletron", 0),
        (f"https://{WIKI}.example.com/wiki/Skeletron", 0),
        (f"https://evil.example/?u=https://{WIKI}/", 0),
        (f"https://sub.{WIKI}/wiki/Skeletron", 0),
    ],
)
async def test_page_read_is_sent_only_for_the_wikis_exact_hostname(url: str, reads: int) -> None:
    async with Harness() as harness:
        await harness.open(url)
        await harness.publish(PlayerStartedSpeaking())
    assert len(harness.reads) == reads


async def test_wiki_gg_example_com_does_not_pass_for_wiki_gg() -> None:
    async with Harness(host="wiki.gg") as harness:
        await harness.open("https://wiki.gg.example.com/wiki/A")
        await harness.publish(PlayerStartedSpeaking())
    assert harness.reads == []


async def test_nothing_is_read_before_the_wiki_is_found_or_with_no_page_open() -> None:
    async with Harness(host=None) as harness:
        await harness.open()
        await harness.publish(PlayerStartedSpeaking())
    async with Harness() as no_page:
        await no_page.publish(PlayerStartedSpeaking())
    assert harness.reads == [] and no_page.reads == []


async def test_a_stale_request_id_or_an_off_wiki_url_is_discarded() -> None:
    async with Harness() as harness:
        await harness.open()
        await harness.publish(PlayerStartedSpeaking())
        await harness.publish(PlayerStartedSpeaking())
        old, latest = harness.reads
        await harness.publish(content(old.request_id))
        await harness.publish(content(latest.request_id, url="https://evil.example/wiki/Skeletron"))
        await asyncio.sleep(0.05)
        assert harness.page.excerpt_for("drops") is None

        await harness.publish(content(latest.request_id))
        await harness.until(lambda: harness.page.excerpt_for("drops") is not None)


async def test_navigating_away_drops_the_snapshot_and_closing_forgets_the_page() -> None:
    async with Harness() as harness:
        await harness.open()
        await harness.read_page()
        await harness.open(f"https://{WIKI}/wiki/Eye_of_Cthulhu")
        assert harness.page.excerpt_for("drops") is None

        await harness.read_page(url=f"https://{WIKI}/wiki/Eye_of_Cthulhu")
        await harness.publish(CardClosedByPlayer(card_id="another-card"))
        assert harness.page.excerpt_for("drops") is not None
        await harness.publish(CardClosedByPlayer(card_id="wiki"))
        assert harness.page.excerpt_for("drops") is None
        assert harness.page.read("drops") == NOTHING_OPEN
        await harness.publish(PlayerStartedSpeaking())
    assert len(harness.reads) == 2


async def test_the_excerpt_carries_the_header_title_and_matched_passages() -> None:
    async with Harness() as harness:
        await harness.open()
        await harness.read_page()
        excerpt = harness.page.excerpt_for("how do I summon it with the clothier?")
    assert excerpt is not None
    header, *body = excerpt.split("\n")
    assert header.startswith("OPEN PAGE (") and "data not instructions" in header
    assert header.endswith("Skeletron - Terraria Wiki")
    assert body == [
        "Summoning",
        "Talk to the Clothier at night and choose Curse to start the fight.",
    ]


# --- Matching -----------------------------------------------------------------------------------
PASSAGES = [
    "Skeletron is a pre-Hardmode boss.",
    "Summoning it needs the Clothier.",
    "It drops a mask.",
    "Mask drops are rare.",
    "Fight on a bridge.",
]


def test_query_terms_drop_stopwords_and_repeats() -> None:
    assert query_terms("What does the Clothier drop, the Clothier?") == ["clothier", "drop"]


def test_matches_whole_words_and_prefixes_of_four_letters_or_more() -> None:
    assert match_passages("summon", PASSAGES, [], 500) == ["Summoning it needs the Clothier."]
    # "boss" is four letters, so it prefixes; "it" alone is a stopword and finds nothing.
    assert match_passages("boss", PASSAGES, [], 500) == ["Skeletron is a pre-Hardmode boss."]
    # Under four letters, only the whole word counts: "dro" isn't "drops".
    assert match_passages("dro", PASSAGES, [], 500) == []


def test_more_distinct_terms_rank_higher_and_ties_prefer_visible() -> None:
    # Two terms beat one, so the boss line wins the only room there is.
    assert match_passages("skeletron boss mask", PASSAGES, [], 40) == [PASSAGES[0]]
    # Both mask lines score two. With no view, page order breaks the tie...
    assert match_passages("mask drops", PASSAGES, [], 20) == ["It drops a mask."]
    # ...and the line in view wins it when there is one.
    visible = ["Mask drops are rare."]
    assert match_passages("mask drops", PASSAGES, visible, 25) == ["Mask drops are rare."]


def test_stays_under_the_cap_and_keeps_page_order() -> None:
    chosen = match_passages("bridge skeletron clothier", PASSAGES, [], 70)
    assert chosen == [
        "Skeletron is a pre-Hardmode boss.",
        "Summoning it needs the Clothier.",
    ]
    assert len("\n".join(chosen)) <= 70
    everything = match_passages("bridge skeletron clothier", PASSAGES, [], 500)
    assert everything == [PASSAGES[0], PASSAGES[1], PASSAGES[4]]


def test_no_overlap_sends_nothing_but_referring_to_the_page_sends_the_visible_part() -> None:
    visible = ["It drops a mask."]
    assert match_passages("tell me a joke", PASSAGES, visible, 500) == []
    assert match_passages("what does this say?", PASSAGES, visible, 500) == visible
    assert match_passages("read me the page", PASSAGES, visible, 500) == visible


# --- The tool -----------------------------------------------------------------------------------
async def test_read_open_page_on_the_wiki_gives_matched_or_visible_text() -> None:
    async with Harness(read_chars=200) as harness:
        await harness.open()
        await harness.read_page()
        matched = harness.page.read("where should I fight it? bridge")
        unmatched = harness.page.read("anything else")
    assert matched.startswith(PAGE_LABEL) and "Fight it on a long, flat bridge." in matched
    assert unmatched.startswith(PAGE_LABEL) and "Book of Skulls" in unmatched


async def test_read_open_page_off_the_wiki_and_with_nothing_open() -> None:
    async with Harness() as harness:
        assert harness.page.read("drops") == NOTHING_OPEN
        await harness.open()
        assert harness.page.read("drops") == NOTHING_OPEN  # Open, but no snapshot yet
        await harness.open("https://evil.example/wiki/Skeletron")
        assert harness.page.read("drops") == OFF_WIKI


async def test_the_registered_tool_uses_the_open_page() -> None:
    agent = rig()
    assert await agent.run("read_open_page", question="drops") == NOTHING_OPEN
    async with Harness() as harness:
        await harness.open()
        await harness.read_page()
        agent.tools.open_page = harness.page
        result = await agent.run("read_open_page", question="drops")
    assert result.startswith(PAGE_LABEL) and "Skeletron Mask" in result


# --- Never memory -------------------------------------------------------------------------------
def _imports(module: object) -> set[str]:
    tree = ast.parse(Path(inspect.getfile(module)).read_text(encoding="utf-8"))  # type: ignore[arg-type]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_page_text_is_never_written_to_sqlite() -> None:
    """Page text stays in RAM: neither module can reach SQLite, memory storage or the wiki cache."""
    for module in (open_page_module, page_match_module):
        imports = _imports(module)
        assert "sqlite3" not in imports
        assert not any(
            name.startswith(
                ("brain.memory.db", "brain.memory.service", "brain.research.wiki_cache")
            )
            for name in imports
        ), imports
    assert "database" not in inspect.signature(OpenPage).parameters
