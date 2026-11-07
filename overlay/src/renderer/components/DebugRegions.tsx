import type { DebugRegion, Rect } from "../../lib/protocol.generated.ts";
import type { Size } from "../logic/layout.ts";
import { placeRegions } from "../logic/debugRegions.ts";

interface DebugRegionsProps {
  regions: DebugRegion[];
  viewport: Size;
}

const box = ({ x, y, width, height }: Rect) => ({
  left: x,
  top: y,
  width,
  height,
});

/**
 * Where each HUD region was found and what its reader reads. Only the labels carry a
 * data-rect-id: the brain masks reported rects, and a masked outline would cover the very box
 * being read.
 */
export function DebugRegions({ regions, viewport }: DebugRegionsProps) {
  if (regions.length === 0) return null;
  return (
    <div className="debug-regions" aria-hidden="true">
      {placeRegions(regions, viewport).map((placed) => (
        <div key={placed.labelRectId} className={`debug-${placed.status}`}>
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
