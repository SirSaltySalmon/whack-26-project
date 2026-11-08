import type { NoteView } from "../../../../lib/protocol.generated.ts";
import { ago } from "../../logic/memory.ts";
import { MemoryItemMenu } from "./MemoryItemMenu.tsx";
import type { ChangeMemory } from "./useMemoryChanges.ts";

export function SessionNoteCard({
  note,
  disabled,
  onChange,
}: {
  note: NoteView;
  disabled: boolean;
  onChange: ChangeMemory;
}) {
  const label = `${note.kind === "recap" ? "Recap" : "Rolling note"} #${note.id}`;
  return (
    <article className="mem-note">
      <header className="mem-note-heading">
        <strong>{label}</strong>
        <span className="mem-meta">{ago(note.created_at)}</span>
      </header>
      <MemoryItemMenu
        id={note.id}
        kind="note"
        text={note.body}
        label={label}
        disabled={disabled}
        onChange={onChange}
      />
      <pre>{note.body}</pre>
    </article>
  );
}
