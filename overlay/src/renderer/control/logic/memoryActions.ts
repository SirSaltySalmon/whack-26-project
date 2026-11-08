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
      return result;
    } finally {
      this.busy = false;
    }
  }
}
