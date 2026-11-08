import { logger } from "../../lib/logger.ts";
import { isUploadedAvatar, type UploadedAvatar } from "../logic/avatars.ts";

/**
 * Uploaded avatars, kept in IndexedDB: the overlay and the Control Center load from the same
 * origin, so both see the same store, and it holds far more than localStorage's few megabytes.
 * Nothing here leaves this computer.
 */
const DB_NAME = "overlay-avatars";
const DB_VERSION = 1;
const STORE = "uploads";
const CHANNEL = "overlay.avatars";

let opening: Promise<IDBDatabase> | null = null;

function open(): Promise<IDBDatabase> {
  if (opening === null) {
    opening = new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        request.result.createObjectStore(STORE, { keyPath: "id" });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () =>
        reject(request.error ?? new Error("Could not open avatar storage"));
    });
    // Forget a failure, so the next call tries again instead of failing forever.
    opening.catch(() => {
      opening = null;
    });
  }
  return opening;
}

/** Runs one request in its own transaction, resolving once the transaction has committed. */
async function inStore<T>(
  mode: IDBTransactionMode,
  makeRequest: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await open();
  return new Promise<T>((resolve, reject) => {
    const transaction = db.transaction(STORE, mode);
    const request = makeRequest(transaction.objectStore(STORE));
    transaction.oncomplete = () => resolve(request.result);
    transaction.onerror = () =>
      reject(
        transaction.error ??
          request.error ??
          new Error("Avatar storage failed"),
      );
    transaction.onabort = () =>
      reject(transaction.error ?? new Error("Avatar storage was interrupted"));
  });
}

export async function listUploads(): Promise<UploadedAvatar[]> {
  const rows: unknown[] = await inStore("readonly", (store) => store.getAll());
  const valid = rows.filter(isUploadedAvatar);
  if (valid.length < rows.length) {
    logger.warn(
      `Ignored ${rows.length - valid.length} saved avatar(s) that weren't valid`,
    );
  }
  return valid;
}

export async function saveUpload(avatar: UploadedAvatar): Promise<void> {
  await inStore("readwrite", (store) => store.put(avatar));
}

export async function deleteUpload(id: string): Promise<void> {
  await inStore("readwrite", (store) => store.delete(id));
}

// One channel per window: a BroadcastChannel never hears its own messages, so each window hears
// only the other's changes, and updates its own state directly.
let channel: BroadcastChannel | null = null;

function shared(): BroadcastChannel | null {
  if (channel === null && typeof BroadcastChannel !== "undefined") {
    channel = new BroadcastChannel(CHANNEL);
  }
  return channel;
}

/** Tells the other window that the uploads or the choice changed, so it reloads them. */
export function announceAvatarChange(): void {
  try {
    shared()?.postMessage("changed");
  } catch (error) {
    logger.warn(
      "Could not tell the other window about the avatar change",
      error,
    );
  }
}

/** Calls `listener` when the other window changes avatars. Returns the unsubscribe. */
export function onAvatarChange(listener: () => void): () => void {
  const current = shared();
  if (current === null) {
    logger.warn(
      "BroadcastChannel is missing, so avatar changes won't sync between windows",
    );
    return () => undefined;
  }
  const handler = (): void => listener();
  current.addEventListener("message", handler);
  return () => current.removeEventListener("message", handler);
}
