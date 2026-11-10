"""Local, manually scripted UI showcase. No capture, microphone, memory writes or AI calls.

Run via render_showcase.cjs. Uses the production WebSocket link and validated protocol.
"""

import uvicorn
from fastapi import HTTPException

from brain.events import EventBus
from brain.server import OverlayLink, create_app
from shared.protocol.messages import (
    AvatarState,
    CardShow,
    DangerState,
    DebugBrain,
    DebugRegion,
    DebugRegions,
    DebugSighting,
    DebugSightings,
    PointerFly,
    Rect,
    SubtitleChunk,
)

link = OverlayLink(EventBus())
app = create_app(link)


def rect(box: tuple[int, int, int, int]) -> Rect:
    x, y, width, height = box
    return Rect(x=x, y=y, width=width, height=height)


async def sightings(objects: list[tuple[str, tuple[int, int, int, int]]]) -> None:
    await link.send(
        DebugSightings(
            sightings=[
                DebugSighting(label=label, rect=rect(box), kind="noticed", ttl_ms=30000)
                for label, box in objects
            ]
        )
    )


async def say(scene: str, text: str) -> None:
    await link.send(AvatarState(state="talking"))
    await link.send(SubtitleChunk(utterance_id=f"manual-showcase-{scene}", text=text, final=True))


async def danger_scene() -> None:
    await link.send(DangerState(level="high"))
    await link.send(
        DebugRegions(
            regions=[
                DebugRegion(
                    name="health (learned)",
                    rect=rect((1594, 12, 146, 40)),
                    status="ok",
                    display="40/100 - LOW",
                )
            ]
        )
    )
    await sightings(
        [
            ("Zombie", (734, 509, 48, 69)),
            ("Zombie", (1110, 405, 66, 71)),
            ("Zombie", (1724, 479, 54, 72)),
            ("Player", (935, 502, 47, 71)),
        ]
    )
    await link.send(
        DebugBrain(
            hearing="I'm low on health. What should I do?",
            hearing_live=False,
            mood="concerned",
            mood_valence=-0.6,
            decision="Danger: low health + zombies",
            doing="Escape warning",
            focus="high",
            latency=[],
        )
    )
    await say("danger", "You're low on health! Get away from those zombies and heal.")


async def wiki_scene() -> None:
    await link.send(
        CardShow(
            card_id="minecraft-wiki",
            title="Smite - Minecraft Wiki",
            body="Smite increases damage against undead mobs, including zombies. "
            "For a sword dedicated to fighting zombies, choose Smite V.",
            source_url="https://minecraft.wiki/w/Smite",
            page_url="https://minecraft.wiki/w/Smite",
        )
    )


async def minecraft_scene() -> None:
    await sightings([("Zombie - undead", (953, 319, 418, 656))])
    await link.send(
        PointerFly(
            x=1120,
            y=425,
            label="Zombie - undead",
            target=rect((1020, 322, 204, 210)),
            ttl_ms=30000,
        )
    )
    await say(
        "minecraft", "Those are zombies. Smite V is the strongest damage enchantment against them."
    )


# Manually annotated on the supplied 1920 x 1080 screenshot, in matching overlay DIPs.
OBJECTS = [
    ("Grandfather clock", (1246, 466, 46, 108)),
    ("Bookshelf", (1114, 122, 136, 207)),
    ("Bed", (691, 286, 98, 43)),
    ("Player", (939, 499, 46, 71)),
    ("Storage chests", (667, 844, 146, 43)),
]


@app.get("/showcase/health")
async def health() -> dict[str, bool]:
    return {"showcase": True, "connected": link.connected}


@app.post("/showcase/{scene}")
async def show(scene: str) -> dict[str, str]:
    if scene not in {"clean", "debug", "danger", "minecraft", "wiki"}:
        raise HTTPException(404, "Unknown showcase scene")
    if not link.connected:
        raise HTTPException(409, "Overlay is not connected")
    if scene == "wiki":
        await wiki_scene()
        return {"scene": scene}
    if scene == "danger":
        await danger_scene()
        return {"scene": scene}
    if scene == "minecraft":
        await minecraft_scene()
        return {"scene": scene}
    await link.send(AvatarState(state="talking"))
    await link.send(
        PointerFly(
            x=1269,
            y=520,
            label="Grandfather clock",
            target=Rect(x=1246, y=466, width=46, height=108),
            ttl_ms=30000,
        )
    )
    await link.send(
        SubtitleChunk(
            utterance_id=f"manual-showcase-{scene}",
            text="The grandfather clock is beside the painting, on the middle floor.",
            final=True,
        )
    )
    if scene == "debug":
        await link.send(
            DebugSightings(
                sightings=[
                    DebugSighting(
                        label=label,
                        rect=Rect(x=x, y=y, width=w, height=h),
                        kind="point" if label == "Grandfather clock" else "noticed",
                        ttl_ms=30000,
                    )
                    for label, (x, y, w, h) in OBJECTS
                ]
            )
        )
    return {"scene": scene}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
