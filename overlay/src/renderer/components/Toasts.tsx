import { useEffect } from "react";
import type { ShownToast } from "../hooks/useCompanionFeed.ts";

const TOAST_MS = 4000;
const SOURCE_LABELS: Record<string, string> = {
  player: "you said",
  observed: "seen on screen",
  wiki: "from the wiki",
};

function Toast({
  shown,
  onDone,
}: {
  shown: ShownToast;
  onDone(id: number): void;
}) {
  useEffect(() => {
    const timer = setTimeout(() => onDone(shown.id), TOAST_MS);
    return () => clearTimeout(timer);
    // The id never changes for a toast, and a new onDone each render shouldn't restart its timer.
  }, [shown.id]);

  return (
    <div className="toast" data-rect-id={`toast-${shown.id}`}>
      <span className="toast-heading">Memory updated</span>
      <span>{shown.toast.text}</span>
      <span className="toast-source">{SOURCE_LABELS[shown.toast.source]}</span>
    </div>
  );
}

export function Toasts({
  toasts,
  onDone,
}: {
  toasts: ShownToast[];
  onDone(id: number): void;
}) {
  return (
    <div className="toasts">
      {toasts.map((shown) => (
        <Toast key={shown.id} shown={shown} onDone={onDone} />
      ))}
    </div>
  );
}
