/** Reading the wiki window's rendered text, for the brain's page.read. Shared by main and tests. */

export const MAX_PAGE_CHARS = 200_000;
export const MAX_VISIBLE_CHARS = 4_000;
export const READ_TIMEOUT_MS = 500;
/**
 * Our own isolated world in the page, so the page's scripts can't see or tamper with the reader.
 * 0 is the page's world and 999 is Electron's, so anything else in range is ours.
 */
export const READ_WORLD_ID = 1729;

export interface PageText {
  url: string;
  title: string | null;
  text: string;
  visible_text: string;
  truncated: boolean;
}

/**
 * Only reads: `innerText` leaves out markup and anything hidden by CSS, and form values aren't
 * part of it. Wiki skins put the article in #mw-content-text, other sites in main or article.
 */
export const READ_PAGE_SCRIPT = `(() => {
  const root = document.querySelector("#mw-content-text, main, article") ?? document.body;
  const full = root.innerText;
  const inView = (e) => { const r = e.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight; };
  const seen = [...root.querySelectorAll("h1,h2,h3,h4,p,li,th,td,dt,dd,figcaption")].filter(inView);
  return {
    text: full.slice(0, ${MAX_PAGE_CHARS}),
    visible_text: seen.map((e) => e.innerText).join("\\n").slice(0, ${MAX_VISIBLE_CHARS}),
    truncated: full.length > ${MAX_PAGE_CHARS},
  };
})()`;

/**
 * The script's result came out of a web page, so check its shape rather than trusting it, and cut
 * it to the protocol's limits again. Returns null for anything that isn't what the script returns.
 */
export function toPageText(
  result: unknown,
  url: string,
  title: string,
): PageText | null {
  if (typeof result !== "object" || result === null) return null;
  const { text, visible_text, truncated } = result as Record<string, unknown>;
  if (typeof text !== "string" || typeof visible_text !== "string") return null;
  return {
    url,
    title: title === "" ? null : title,
    text: text.slice(0, MAX_PAGE_CHARS),
    visible_text: visible_text.slice(0, MAX_VISIBLE_CHARS),
    truncated: truncated === true || text.length > MAX_PAGE_CHARS,
  };
}

/** Resolves to null if the work takes longer than `ms`, so a hung page can't hold up a turn. */
export function withTimeout<T>(
  work: Promise<T>,
  ms: number,
): Promise<T | null> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => resolve(null), ms);
    work.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}
