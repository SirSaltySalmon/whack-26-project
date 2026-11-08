import type {
  MemoryAdminRequest,
  MemoryAdminResult,
} from "../../../lib/protocol.generated.ts";

type Send = (request: MemoryAdminRequest) => Promise<MemoryAdminResult>;

/** A refresh must never race a write and restore its older snapshot on screen. */
export class MemoryActions {
  busy = false;

  async run(
    request: MemoryAdminRequest,
    send: Send,
  ): Promise<MemoryAdminResult | null> {
    if (this.busy) return null;
    this.busy = true;
    try {
      const result = await send(request);
      if (
        request.operation === "forget" &&
        result.facts.some((fact) => fact.id === request.fact_id)
      ) {
        throw new Error(
          "The fact is still current. Forget was not saved; please refresh and retry.",
        );
      }
      if (
        request.operation === "delete_note" &&
        result.note_items?.some((note) => note.id === request.note_id)
      ) {
        throw new Error(
          "The note is still present. Deletion was not saved; please refresh and retry.",
        );
      }
      if (
        request.operation === "edit_note" &&
        !result.note_items?.some(
          (note) => note.id === request.note_id && note.body === request.body,
        )
      ) {
        throw new Error(
          "The edited note was not returned. Please refresh to verify the saved text.",
        );
      }
      return result;
    } finally {
      this.busy = false;
    }
  }
}
