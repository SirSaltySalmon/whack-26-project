import { useEffect, useState } from "react";
import type { DangerSignal } from "../hooks/useCompanionFeed.ts";

// Long enough to notice, short enough not to sit over a fight that lasts minutes.
const SHOW_MS = 4000;
const LABELS = { medium: "Heads up", high: "Danger" } as const;

/**
 * A small pill at the top and one brief glow at the screen edges when danger starts or rises.
 * The pill is masked like any element. The glow isn't, because masking the screen edges would hide
 * the game's own health bars, so it stays faint and fades within two seconds.
 */
export function DangerAlert({ danger }: { danger: DangerSignal | null }) {
  const [expiredSeq, setExpiredSeq] = useState<number | null>(null);

  useEffect(() => {
    if (danger === null || danger.level === "none") return;
    const timer = setTimeout(() => setExpiredSeq(danger.seq), SHOW_MS);
    return () => clearTimeout(timer);
  }, [danger]);

  if (danger === null || danger.level === "none" || danger.seq === expiredSeq) {
    return null;
  }
  return (
    <>
      <div
        key={`glow-${danger.seq}`}
        className="danger-glow"
        data-level={danger.level}
        aria-hidden="true"
      />
      <div
        key={`alert-${danger.seq}`}
        className="danger-alert"
        data-level={danger.level}
        data-rect-id="danger"
        role="status"
      >
        <span className="danger-dot" />
        {LABELS[danger.level]}
      </div>
    </>
  );
}
