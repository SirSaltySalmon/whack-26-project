import { useCallback, useRef } from "react";
import { logger } from "../../lib/logger.ts";
import type { BrainSocket } from "../lib/brainSocket.ts";

/**
 * Answers the brain's page.read with the wiki window's text. The brain decides whether a page may
 * be read at all; this only reads whatever is open. A minimized window still counts as open.
 * With no window, or a failed or slow read, nothing is sent and the brain's turn goes on without it.
 */
export function usePageReader(
  socket: BrainSocket | null,
  wikiCardId: string | undefined,
): (requestId: string) => void {
  const latest = useRef({ socket, wikiCardId });
  latest.current = { socket, wikiCardId };

  return useCallback((requestId: string): void => {
    const cardId = latest.current.wikiCardId;
    if (cardId === undefined) {
      logger.info("Asked to read the page, but no wiki window is open");
      return;
    }
    window.overlay
      .readPage()
      .then((page) => {
        if (page === null) {
          logger.info("Page read gave nothing, so no reply was sent");
          return;
        }
        latest.current.socket?.send({
          type: "page.content",
          request_id: requestId,
          card_id: cardId,
          ...page,
        });
      })
      .catch((error: unknown) => logger.warn("Page read failed", error));
  }, []);
}
