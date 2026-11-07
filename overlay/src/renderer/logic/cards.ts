import type { Frame } from "./layout.ts";

export interface PageState {
  /** Bumped per request, so asking for the same page again still navigates back to it. */
  requestSeq: number;
  requestedUrl: string;
  currentUrl: string | null;
  pageTitle: string | null;
}

export interface Card {
  id: string;
  title: string;
  body: string;
  page: PageState | null;
  minimized: boolean;
  frame: Frame;
  /** Stacking order, highest on top. */
  z: number;
}

export interface ShowCard {
  id: string;
  title: string;
  body: string;
  pageUrl: string | null;
  /** Used only for a card that doesn't exist yet. Reused cards stay where the player put them. */
  frame: Frame;
}

export type CardAction =
  | { kind: "show"; card: ShowCard }
  | { kind: "update"; id: string; title?: string | null; body?: string | null }
  | { kind: "close"; id: string }
  | { kind: "minimize"; id: string; minimized: boolean }
  | { kind: "raise"; id: string }
  | { kind: "frame"; id: string; frame: Frame }
  | { kind: "navigated"; id: string; url: string; title?: string | null };

function newPage(url: string, previous: PageState | null): PageState {
  return {
    requestSeq: (previous?.requestSeq ?? 0) + 1,
    requestedUrl: url,
    currentUrl: previous?.currentUrl ?? null,
    pageTitle: null,
  };
}

const topZ = (cards: Card[]): number =>
  cards.reduce((top, card) => Math.max(top, card.z + 1), 0);

function show(
  cards: Card[],
  { id, title, body, pageUrl, frame }: ShowCard,
): Card[] {
  // There's one wiki window, so a new page reuses it instead of stacking another on the game.
  const existing =
    cards.find((card) => card.id === id) ??
    (pageUrl === null ? undefined : cards.find((card) => card.page !== null));
  const page =
    pageUrl === null
      ? (existing?.page ?? null)
      : newPage(pageUrl, existing?.page ?? null);
  const shown: Card = {
    id,
    title,
    body,
    page,
    minimized: false,
    frame: existing?.frame ?? frame,
    z: topZ(cards),
  };
  return existing
    ? cards.map((card) => (card === existing ? shown : card))
    : [...cards, shown];
}

/**
 * Array order never changes for a card that stays. Reordering would move its DOM node, which drops
 * pointer capture mid-drag and makes a webview reload its page, so stacking lives in `z`.
 */
export function cardsReducer(cards: Card[], action: CardAction): Card[] {
  const change = (id: string, patch: (card: Card) => Card): Card[] =>
    cards.map((card) => (card.id === id ? patch(card) : card));

  switch (action.kind) {
    case "show":
      return show(cards, action.card);
    case "update":
      return change(action.id, (card) => ({
        ...card,
        title: action.title ?? card.title,
        body: action.body ?? card.body,
      }));
    case "close":
      return cards.filter((card) => card.id !== action.id);
    case "minimize":
      return change(action.id, (card) => ({
        ...card,
        minimized: action.minimized,
      }));
    case "raise": {
      const raised = cards.find((card) => card.id === action.id);
      if (!raised || raised.z === Math.max(...cards.map((card) => card.z))) {
        return cards;
      }
      return change(action.id, (card) => ({ ...card, z: topZ(cards) }));
    }
    case "frame":
      return change(action.id, (card) => ({ ...card, frame: action.frame }));
    case "navigated":
      return change(action.id, (card) =>
        card.page
          ? {
              ...card,
              page: {
                ...card.page,
                currentUrl: action.url,
                pageTitle: action.title ?? card.page.pageTitle,
              },
            }
          : card,
      );
  }
}
