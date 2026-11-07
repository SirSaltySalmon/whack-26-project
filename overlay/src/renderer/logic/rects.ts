import type { ElementRect } from "../../lib/protocol.generated.ts";

/** Hidden or empty elements have nothing to mask. */
export function visibleRects(rects: ElementRect[]): ElementRect[] {
  return rects.filter(({ rect }) => rect.width > 0 && rect.height > 0);
}

export function sameRects(a: ElementRect[], b: ElementRect[]): boolean {
  return (
    a.length === b.length &&
    a.every((item, index) => {
      const other = b[index];
      return (
        other !== undefined &&
        item.element_id === other.element_id &&
        item.rect.x === other.rect.x &&
        item.rect.y === other.rect.y &&
        item.rect.width === other.rect.width &&
        item.rect.height === other.rect.height
      );
    })
  );
}
