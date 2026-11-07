/** Shared by the main process's guards and the renderer, so both apply the same rules. */

/** In-memory on purpose (no `persist:` prefix): the page keeps no login between runs. */
export const WEB_PARTITION = "wiki";

/** Links may go anywhere, but other schemes (file:, javascript:, app links) never load. */
export function isWebUrl(url: string): boolean {
  try {
    const { protocol } = new URL(url);
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}
