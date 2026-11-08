/* Memory lives on disk, so it can be read with the partner off. Kept out of ControlContext so
   it's tested directly. */
import {
  isMemoryRequest,
  type ControlBridge,
} from "../../../lib/controlBridge.ts";
import type { Askable, ReplyOf, ReplyType } from "../api.ts";

/** Answers a request with no brain connected: memory requests only, through the main process. */
export async function readMemory<T extends ReplyType>(
  bridge: Pick<ControlBridge, "memory">,
  message: Askable,
  expect: T,
): Promise<ReplyOf<T>> {
  if (!isMemoryRequest(message)) throw new Error("The brain isn't connected");
  const answer = await bridge.memory(message);
  if (!answer.ok) throw new Error(answer.error);
  if (answer.reply.type !== expect) {
    throw new Error(`Expected ${expect}, got ${answer.reply.type}`);
  }
  return answer.reply as ReplyOf<T>;
}
