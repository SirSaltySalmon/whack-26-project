import type { PlayerText } from "../../lib/protocol.generated.ts";

/** Keep equal to PlayerText.text's max_length in shared/protocol/messages.py. */
export const CHAT_MAX_CHARS = 500;

export const CHAT_OFFLINE_HINT = "Waiting for the brain to connect";

/** The turn to send for what the player typed, or null when there's nothing to say. */
export function playerText(draft: string): PlayerText | null {
  // Code points, not UTF-16 units, because that's what the brain's length check counts, and a
  // cut can't split an emoji in half.
  const text = Array.from(draft.trim())
    .slice(0, CHAT_MAX_CHARS)
    .join("")
    .trim();
  return text === "" ? null : { type: "player.text", text };
}

export type ChatKey =
  { action: "send"; turn: PlayerText } | { action: "close" } | null;

/**
 * What a key in the chat box does. Enter on an empty box closes it too, as in most game chats, so
 * Enter out always hands the keyboard back to the game.
 */
export function chatKey(key: string, draft: string): ChatKey {
  if (key === "Escape") return { action: "close" };
  if (key !== "Enter") return null;
  const turn = playerText(draft);
  return turn === null ? { action: "close" } : { action: "send", turn };
}
