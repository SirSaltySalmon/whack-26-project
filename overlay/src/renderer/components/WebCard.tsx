import { useEffect, useState } from "react";
import { WEB_PARTITION } from "../../lib/web.ts";
import { useWebPage } from "../hooks/useWebPage.ts";
import type { Card } from "../logic/cards.ts";
import { WEB_CARD_LIMITS, type Frame } from "../logic/layout.ts";
import { CardWindow } from "./CardWindow.tsx";

interface WebCardProps {
  card: Card;
  page: NonNullable<Card["page"]>;
  zIndex: number;
  onFrame(frame: Frame): void;
  onFrameEnd(frame: Frame): void;
  onRaise(): void;
  onMinimize(): void;
  onClose(): void;
  onNavigated(url: string, title?: string): void;
}

/**
 * Without this, links that open a new window do nothing. No window opens: pageGuard.ts denies it
 * and loads the link in this one. It's a string because React drops `true` on this attribute, even
 * though React's types ask for a boolean.
 */
const POPUPS_LOAD_HERE = { allowpopups: "true" } as unknown as {
  allowpopups: boolean;
};

/** True while the overlay window has keyboard focus, which only happens when the player asks. */
function useWindowFocused(): boolean {
  const [focused, setFocused] = useState(document.hasFocus());
  useEffect(() => {
    const onFocus = (): void => setFocused(true);
    const onBlur = (): void => setFocused(false);
    window.addEventListener("focus", onFocus);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("blur", onBlur);
    };
  }, []);
  return focused;
}

/** The real site, sandboxed by pageGuard.ts in the main process. Its title is untrusted text. */
export function WebCard({
  card,
  page,
  zIndex,
  onNavigated,
  ...windowProps
}: WebCardProps) {
  const view = useWebPage({
    requestedUrl: page.requestedUrl,
    requestSeq: page.requestSeq,
    onNavigated,
  });
  const typing = useWindowFocused();

  const requestTyping = (): void => {
    window.overlay.requestTyping();
    view.focus();
  };

  const controls = (
    <div
      className="card-buttons"
      onPointerDown={(event) => event.stopPropagation()}
    >
      <button
        type="button"
        title="Back"
        aria-label="Back"
        disabled={!view.canGoBack}
        onClick={view.goBack}
      >
        ←
      </button>
      <button
        type="button"
        title="Forward"
        aria-label="Forward"
        disabled={!view.canGoForward}
        onClick={view.goForward}
      >
        →
      </button>
      <button
        type="button"
        title="Reload"
        aria-label="Reload"
        onClick={view.reload}
      >
        ↻
      </button>
      <button
        type="button"
        className={typing ? "active" : undefined}
        title="Type into this page. The game gets no keys until you click back into it."
        aria-label="Type into this page"
        onClick={requestTyping}
      >
        ⌨
      </button>
    </div>
  );

  return (
    <CardWindow
      rectId="wiki-window"
      title={page.pageTitle ?? card.title}
      frame={card.frame}
      limits={WEB_CARD_LIMITS}
      zIndex={zIndex}
      hidden={card.minimized}
      controls={controls}
      {...windowProps}
    >
      <webview
        ref={view.ref}
        className="card-page"
        src={view.initialUrl}
        partition={WEB_PARTITION}
        {...POPUPS_LOAD_HERE}
      />
      {view.loading && <div className="card-loading" aria-hidden="true" />}
      {view.failed && (
        <div className="card-text card-fallback">
          <p className="card-fallback-note">
            This page couldn't load. Use ↻ to try again.
          </p>
          {card.body}
        </div>
      )}
    </CardWindow>
  );
}
