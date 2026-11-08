import { motion } from "motion/react";
import { useEffect, useState } from "react";
import type { Size } from "../logic/layout.ts";
import { placePointer, type TargetBox } from "../logic/pointerPlacement.ts";

const DEFAULT_TTL_MS = 6000;
const MIN_TTL_MS = 500;
const MAX_TTL_MS = 30000;

export interface PointerCommand {
  /** Bumped per command, so pointing at the same place again restarts the timer. */
  seq: number;
  x: number;
  y: number;
  label: string | null;
  target: TargetBox | null;
  ttlMs: number | null;
}

interface PointerProps {
  command: PointerCommand | null;
  /** Where it launches from and returns to: the middle of the character. */
  home: { x: number; y: number };
  viewport: Size;
}

/** Never catches clicks. It always fades on its own, so a lost `pointer.hide` can't strand it. */
export function Pointer({ command, home, viewport }: PointerProps) {
  const [expiredSeq, setExpiredSeq] = useState<number | null>(null);
  const [parked, setParked] = useState(true);
  const active = command !== null && command.seq !== expiredSeq;

  useEffect(() => {
    if (!command) return;
    const ttl = Math.min(
      Math.max(command.ttlMs ?? DEFAULT_TTL_MS, MIN_TTL_MS),
      MAX_TTL_MS,
    );
    const timer = setTimeout(() => setExpiredSeq(command.seq), ttl);
    return () => clearTimeout(timer);
  }, [command]);

  useEffect(() => {
    if (active) setParked(false);
  }, [active]);

  const placement = active
    ? placePointer(command, command.target, viewport)
    : null;
  const flipX = placement?.flipX ?? false;
  const flipY = placement?.flipY ?? false;

  return (
    <motion.div
      className="pointer"
      initial={{ x: home.x, y: home.y, opacity: 0, scale: 0.5 }}
      animate={
        placement
          ? { x: placement.x, y: placement.y, opacity: 1, scale: 1 }
          : { x: home.x, y: home.y, opacity: 0, scale: 0.5 }
      }
      transition={{ type: "spring", stiffness: 170, damping: 22 }}
      onAnimationComplete={() => {
        if (!active) setParked(true);
      }}
    >
      {/* Unreported once parked: it's invisible at home, and masking it would hide the character. */}
      <div
        // pointer-on lets skins run idle motion only while it's shown, not forever while parked.
        className={`pointer-body${active ? " pointer-on" : ""}${flipX ? " flip-x" : ""}${flipY ? " flip-y" : ""}`}
        data-rect-id={parked ? undefined : "pointer"}
      >
        <svg className="pointer-arrow" viewBox="0 0 40 40" aria-hidden="true">
          <path d="M0 0 L36 13 L20 20 L13 36 Z" />
        </svg>
        {active && command.label && (
          <span className="pointer-label">{command.label}</span>
        )}
      </div>
    </motion.div>
  );
}
