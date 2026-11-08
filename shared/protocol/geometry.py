"""Shapes shared by the messages. Coordinates are Electron DIPs."""

from pydantic import BaseModel


class Rect(BaseModel):
    x: float
    y: float
    width: float
    height: float


class ElementRect(BaseModel):
    element_id: str
    rect: Rect
