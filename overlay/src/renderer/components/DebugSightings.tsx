import type { Rect } from "../../lib/protocol.generated.ts";
import type { Size } from "../logic/layout.ts";
import { placeSightings, type ShownSighting } from "../logic/debugSightings.ts";

interface DebugSightingsProps {
  sightings: ShownSighting[];
  viewport: Size;
}

const box = ({ x, y, width, height }: Rect) => ({
  left: x,
  top: y,
  width,
  height,
});

/**
 * Where the models looked and what they noticed. As in DebugRegions, only the labels carry a
 * data-rect-id: masked labels keep the observer from reading its own boxes' names back as on-screen
 * text, and an unmasked outline keeps the thing it surrounds visible to the next look.
 */
export function DebugSightings({ sightings, viewport }: DebugSightingsProps) {
  if (sightings.length === 0) return null;
  return (
    <div className="debug-regions" aria-hidden="true">
      {placeSightings(sightings, viewport).map((placed) => (
        <div
          key={placed.id}
          className={`debug-sighting sighting-${placed.kind}`}
          style={{
            animationDelay: `${placed.fadeDelayMs}ms`,
            animationDuration: `${placed.fadeMs}ms`,
          }}
        >
          <div className="debug-outline" style={box(placed.outline)} />
          <div
            className="debug-label"
            data-rect-id={placed.labelRectId}
            style={box(placed.label)}
          >
            {placed.labelText}
          </div>
        </div>
      ))}
    </div>
  );
}
