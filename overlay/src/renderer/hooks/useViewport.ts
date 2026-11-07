import { useEffect, useState } from "react";
import type { Size } from "../logic/layout.ts";

const read = (): Size => ({
  width: window.innerWidth,
  height: window.innerHeight,
});

export function useViewport(): Size {
  const [viewport, setViewport] = useState(read);
  useEffect(() => {
    const update = (): void => setViewport(read());
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return viewport;
}
