import { useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { menuPosition } from "../../logic/menuPosition.ts";
import { useMemoryMenu } from "./MemoryMenuContext.tsx";
import type { ChangeMemory } from "./useMemoryChanges.ts";

export function MemoryItemMenu({
  id,
  kind,
  text,
  label,
  disabled,
  onChange,
}: {
  id: number;
  kind: "fact" | "note";
  text: string;
  label: string;
  disabled: boolean;
  onChange: ChangeMemory;
}) {
  const menuId = useId();
  const { open, setOpen } = useMemoryMenu(menuId);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  useLayoutEffect(() => {
    if (!open) return;
    const update = () => {
      if (!trigger.current || !panel.current) return;
      setPosition(
        menuPosition(
          trigger.current.getBoundingClientRect(),
          panel.current.getBoundingClientRect(),
          {
            width: window.innerWidth,
            height: window.innerHeight,
          },
        ),
      );
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open]);
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [draft, setDraft] = useState(text);
  const remove = async () => {
    const ok = await onChange(
      kind === "fact"
        ? { operation: "forget", fact_id: id }
        : { operation: "delete_note", note_id: id, expected_body: text },
    );
    if (ok) {
      setConfirming(false);
      setOpen(false);
    }
  };
  return (
    <div className="mem-item-actions">
      <button
        ref={trigger}
        id={`${menuId}-trigger`}
        className="mem-menu-trigger"
        type="button"
        data-memory-menu={menuId}
        aria-label={`Actions for ${label}`}
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen(!open)}
        title={
          disabled
            ? "Stop the partner before editing memory"
            : `Actions for ${label}`
        }
      >
        ⋯
      </button>
      {open &&
        createPortal(
          <div
            ref={panel}
            id={menuId}
            className="mem-menu-options"
            data-memory-menu={menuId}
            style={position}
          >
            <button
              className="cc-button"
              type="button"
              disabled={disabled}
              onClick={() => {
                setDraft(text);
                setEditing(true);
                setConfirming(false);
                setOpen(false);
              }}
            >
              Edit
            </button>
            <button
              className="cc-button"
              type="button"
              disabled={disabled}
              onClick={() => {
                setEditing(false);
                if (kind === "note") {
                  setConfirming(true);
                  setOpen(false);
                } else void remove();
              }}
            >
              {kind === "fact" ? "Forget" : "Delete note"}
            </button>
          </div>,
          document.body,
        )}
      {editing && (
        <form
          className="mem-inline-editor"
          onSubmit={async (event) => {
            event.preventDefault();
            const ok = await onChange(
              kind === "fact"
                ? { operation: "remember", fact_id: id, value: draft }
                : {
                    operation: "edit_note",
                    note_id: id,
                    body: draft,
                    expected_body: text,
                  },
            );
            if (ok) setEditing(false);
          }}
        >
          <textarea
            className="cc-input"
            aria-label={`Edit ${label}`}
            value={draft}
            rows={kind === "note" ? 6 : 2}
            maxLength={kind === "note" ? 20000 : 2000}
            required
            disabled={disabled}
            onChange={(event) => setDraft(event.target.value)}
          />
          <button
            className="cc-button"
            type="submit"
            disabled={disabled || !draft.trim()}
          >
            Save
          </button>{" "}
          <button
            className="cc-button"
            type="button"
            disabled={disabled}
            onClick={() => setEditing(false)}
          >
            Cancel
          </button>
        </form>
      )}
      {confirming && (
        <div className="mem-inline-editor">
          <p>
            Delete this session note? This removes it from saved notes and
            recall. Facts and recorded conversations are kept.
          </p>
          <button
            className="cc-button"
            type="button"
            disabled={disabled}
            onClick={() => void remove()}
          >
            Delete note
          </button>{" "}
          <button
            className="cc-button"
            type="button"
            disabled={disabled}
            onClick={() => setConfirming(false)}
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
