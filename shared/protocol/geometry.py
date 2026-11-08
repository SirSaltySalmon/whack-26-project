"""Shapes shared by several message modules. Coordinates are Electron DIPs."""

from pydantic import BaseModel


class Rect(BaseModel):
    x: float
    y: float
    width: float
    height: float
