import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { PlayerText } from "../../lib/protocol.generated.ts";
import { CHAT_MAX_CHARS, CHAT_OFFLINE_HINT, chatKey } from "../logic/chat.ts";
import {
  CHAT_BOX_SIZE,
  CHAT_PILL_SIZE,
  chatPosition,
  type Frame,
  type Size,
} from "../logic/layout.ts";

interface ChatBoxProps {
  open: boolean;
  /** With the mic off, the closed box stays as a pill beside the character, one click away. */
  pinned: boolean;
  connected: boolean;
  avatar: Frame;
  viewport: Size;
  onOpen(): void;
  onClose(): void;
  onSend(turn: PlayerText): void;
}

/**
 * The overlay only takes the keyboard while this is open. The game gets it back on Enter or
 * Escape, or when the player clicks back into the game. The draft survives closing, so a turn
 * interrupted by a fight isn't lost.
 */
export function ChatBox({
  open,
  pinned,
  connected,
  avatar,
  viewport,
  onOpen,
  onClose,
  onSend,
}: ChatBoxProps) {
  const [draft, setDraft] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });

  useEffect(() => {
    if (open) window.overlay.requestTyping();
  }, [open]);

  useEffect(() => {
    if (!open || !connected) return;
    const focusInput = (): void => input.current?.focus();
    focusInput();
    // The window gets the keyboard a moment after asking, so focus again once it has.
    window.addEventListener("focus", focusInput);
    return () => window.removeEventListener("focus", focusInput);
  }, [open, connected]);

  useEffect(() => {
    if (!open) return;
    // Fires when the player clicks back into the game, or into the wiki page.
    const onBlur = (): void => close.current();
    window.addEventListener("blur", onBlur);
    return () => window.removeEventListener("blur", onBlur);
  }, [open]);

  if (!open) {
    if (!pinned) return null;
    const at = chatPosition(avatar, CHAT_PILL_SIZE, viewport);
    return (
      <button
        className="chat-pill"
        data-interactive
        data-rect-id="chat"
        type="button"
        style={{ left: at.x, top: at.y }}
        disabled={!connected}
        title={connected ? "Type to your partner" : CHAT_OFFLINE_HINT}
        onClick={onOpen}
      >
        ⌨ {connected ? "Type to talk" : "Not connected"}
      </button>
    );
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    // Enter while an IME is composing picks a word; it isn't a send.
    if (event.nativeEvent.isComposing) return;
    const key = chatKey(event.key, draft);
    if (key === null) return;
    event.preventDefault();
    if (key.action === "send") {
      onSend(key.turn);
      setDraft("");
    }
    onClose();
    // Without this the game stays deaf to the keyboard until the player clicks it.
    window.overlay.endTyping();
  };

  const at = chatPosition(avatar, CHAT_BOX_SIZE, viewport);
  return (
    <div
      className="chat-box"
      data-interactive
      data-rect-id="chat"
      style={{ left: at.x, top: at.y }}
    >
      <span className="chat-glyph" aria-hidden="true">
        ⌨
      </span>
      <input
        ref={input}
        className="chat-input"
        type="text"
        value={draft}
        maxLength={CHAT_MAX_CHARS}
        disabled={!connected}
        placeholder={
          connected ? "Say something, Enter to send" : CHAT_OFFLINE_HINT
        }
        aria-label="Type to your partner"
        spellCheck={false}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={onKeyDown}
      />
    </div>
  );
}
