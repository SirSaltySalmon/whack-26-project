"""Manual check of wiki research against the live web.

python -m scripts.wiki_lookup "Terraria" "Eye of Cthulhu" "how to summon skeletron"
"""

import argparse
import asyncio
import logging

from brain.research import WikiResearch, card_message


async def main(game: str, queries: list[str], api_url: str | None) -> None:
    research = await WikiResearch.for_game(game, override_api_url=api_url)
    if research is None:
        logging.error("No wiki found for %r", game)
        return
    logging.info("Using %s at %s", research.site.info.name, research.site.api_url)
    try:
        for query in queries:
            card = await research.lookup(query)
            if card is None:
                logging.warning("No card for %r", query)
                continue
            logging.info(
                "%s\n%s",
                card_message(card).model_dump_json(indent=2),
                f"image: {card.image_url}",
            )
    finally:
        await research.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("game")
    parser.add_argument("queries", nargs="+")
    parser.add_argument("--api-url", help="Skip discovery and use this api.php")
    args = parser.parse_args()
    asyncio.run(main(args.game, args.queries, args.api_url))
