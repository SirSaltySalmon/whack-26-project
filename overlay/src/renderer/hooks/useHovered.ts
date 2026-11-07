import { useEffect, useState } from "react";
import type { Frame } from "../logic/layout.ts";

/**
 * Uses the same forwarded mouse moves as click-through instead of CSS :hover, so the controls can't
 * disagree with what actually catches clicks.
 */
export function useHovered(frame: Frame): boolean {
  const [hovered, setHovered] = useState(false);
  useEffect(() => {
    const onMove = ({ clientX: x, clientY: y }: MouseEvent): void => {
      setHovered(
        x >= frame.x &&
          x < frame.x + frame.width &&
          y >= frame.y &&
          y < frame.y + frame.height,
      );
    };
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, [frame]);
  return hovered;
}
