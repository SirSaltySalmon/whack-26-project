import { useCallback, useReducer, useRef, useState } from "react";
import { logger } from "../lib/logger.ts";
import type { Brain, CardShow, State } from "../lib/protocol.generated.ts";
import { isWebUrl } from "../lib/web.ts";
import { Avatar } from "./components/Avatar.tsx";
import { CardWindow } from "./components/CardWindow.tsx";
import { Pointer, type PointerCommand } from "./components/Pointer.tsx";
import { QuestionPrompt } from "./components/QuestionPrompt.tsx";
import { SettingsPanel } from "./components/SettingsPanel.tsx";
import { Subtitles } from "./components/Subtitles.tsx";
import { Toasts } from "./components/Toasts.tsx";
import { WebCard } from "./components/WebCard.tsx";
import { useAvatars } from "./hooks/useAvatars.ts";
import { useBrainLink } from "./hooks/useBrainLink.ts";
import { useClickThrough } from "./hooks/useClickThrough.ts";
import { useCompanionFeed } from "./hooks/useCompanionFeed.ts";
import { usePageReader } from "./hooks/usePageReader.ts";
import { useRectReporter } from "./hooks/useRectReporter.ts";
import { useViewport } from "./hooks/useViewport.ts";
import {
  savedAvatarFrame,
  savedLastPage,
  savedWebFrame,
} from "./lib/storage.ts";
import { cardsReducer, type Card } from "./logic/cards.ts";
import {
  clampFrame,
  defaultAvatarFrame,
  defaultSettingsFrame,
  defaultTextFrame,
  defaultWebFrame,
  minimizedTabPosition,
  questionPlacement,
  TEXT_CARD_LIMITS,
} from "./logic/layout.ts";

/** A wiki window the player reopened themselves has no brain-issued id. */
const REOPENED_CARD_ID = "wiki-reopened";

function hostOf(url: string): string {
  return isWebUrl(url) ? new URL(url).host : url;
}

export function App() {
  const viewport = useViewport();
  const [avatarState, setAvatarState] = useState<State>("idle");
  const [avatarSaved, setAvatarFrame] = useState(
    () => savedAvatarFrame.load() ?? defaultAvatarFrame(viewport),
  );
  const [pointer, setPointer] = useState<PointerCommand | null>(null);
  const pointerSeq = useRef(0);
  const [cards, dispatch] = useReducer(cardsReducer, []);
  const [lastPage, setLastPage] = useState(savedLastPage.load);
  const feed = useCompanionFeed();
  const avatars = useAvatars();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsFrame, setSettingsFrame] = useState(() =>
    defaultSettingsFrame(viewport),
  );

  useClickThrough();

  const showCard = (message: CardShow): void => {
    let pageUrl = message.page_url ?? null;
    if (pageUrl !== null && !isWebUrl(pageUrl)) {
      logger.warn(`Ignored page_url that isn't http or https: ${pageUrl}`);
      pageUrl = null;
    }
    dispatch({
      kind: "show",
      card: {
        id: message.card_id,
        title: message.title,
        body: message.body,
        pageUrl,
        frame:
          pageUrl === null
            ? defaultTextFrame(viewport, cards.length)
            : (savedWebFrame.load() ?? defaultWebFrame(viewport)),
      },
    });
  };

  const onMessage = (message: Brain): void => {
    switch (message.type) {
      case "avatar.state":
        setAvatarState(message.state);
        break;
      case "pointer.fly":
        pointerSeq.current += 1;
        setPointer({
          seq: pointerSeq.current,
          x: message.x,
          y: message.y,
          label: message.label ?? null,
          target: message.target ?? null,
          ttlMs: message.ttl_ms ?? null,
        });
        break;
      case "pointer.hide":
        setPointer(null);
        break;
      case "card.show":
        showCard(message);
        break;
      case "card.update":
        dispatch({
          kind: "update",
          id: message.card_id,
          title: message.title,
          body: message.body,
        });
        break;
      case "card.close":
        dispatch({ kind: "close", id: message.card_id });
        break;
      case "page.read":
        readPage(message.request_id);
        break;
      default:
        feed.handle(message);
    }
  };

  const link = useBrainLink(onMessage);
  useRectReporter(link.socket, link.generation);
  const readPage = usePageReader(
    link.socket,
    cards.find((card) => card.page !== null)?.id,
  );

  const closeCard = (card: Card): void => {
    dispatch({ kind: "close", id: card.id });
    link.socket?.send({ type: "card.closed", card_id: card.id });
  };

  const socket = link.socket;
  const pageChanged = useCallback(
    (id: string, url: string, title?: string): void => {
      dispatch({ kind: "navigated", id, url, title });
      setLastPage(url);
      savedLastPage.save(url);
      socket?.send({
        type: "card.navigated",
        card_id: id,
        url,
        title: title ?? null,
      });
    },
    [socket],
  );

  const avatarFrame = clampFrame(avatarSaved, viewport);
  const webCard = cards.find((card) => card.page !== null);
  const home = {
    x: avatarFrame.x + avatarFrame.width / 2,
    y: avatarFrame.y + avatarFrame.height / 2,
  };
  const tab = minimizedTabPosition(avatarFrame, viewport);

  const reopenWiki =
    lastPage !== null && webCard === undefined
      ? () =>
          dispatch({
            kind: "show",
            card: {
              id: REOPENED_CARD_ID,
              title: hostOf(lastPage),
              body: "",
              pageUrl: lastPage,
              frame: savedWebFrame.load() ?? defaultWebFrame(viewport),
            },
          })
      : null;

  return (
    <>
      <Avatar
        frame={avatarFrame}
        state={avatarState}
        look={avatars.look}
        onFrame={setAvatarFrame}
        onFrameEnd={savedAvatarFrame.save}
        onOpenWiki={reopenWiki}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      {cards.map((card) => {
        const frame = clampFrame(card.frame, viewport);
        const common = {
          zIndex: 10 + card.z,
          onFrame: (next: typeof frame) =>
            dispatch({ kind: "frame", id: card.id, frame: next }),
          onRaise: () => dispatch({ kind: "raise", id: card.id }),
          onClose: () => closeCard(card),
        };
        return card.page ? (
          <WebCard
            // Keyed by slot, not id: a new lookup must reuse this webview, not reload a new one.
            key="wiki-window"
            card={{ ...card, frame }}
            page={card.page}
            onFrameEnd={savedWebFrame.save}
            onMinimize={() =>
              dispatch({ kind: "minimize", id: card.id, minimized: true })
            }
            onNavigated={(url, title) => pageChanged(card.id, url, title)}
            {...common}
          />
        ) : (
          <CardWindow
            key={card.id}
            rectId={`card-${card.id}`}
            title={card.title}
            frame={frame}
            limits={TEXT_CARD_LIMITS}
            {...common}
          >
            <div className="card-text">{card.body}</div>
          </CardWindow>
        );
      })}

      {webCard?.minimized && (
        <button
          className="minimized-tab"
          data-interactive
          data-rect-id="wiki-tab"
          type="button"
          style={{ left: tab.x, top: tab.y }}
          title={webCard.page?.pageTitle ?? webCard.title}
          onClick={() =>
            dispatch({ kind: "minimize", id: webCard.id, minimized: false })
          }
        >
          {webCard.page?.pageTitle ?? webCard.title}
        </button>
      )}

      {settingsOpen && (
        <SettingsPanel
          state={feed.settings}
          avatars={avatars}
          frame={clampFrame(settingsFrame, viewport)}
          onFrame={setSettingsFrame}
          onChange={(settings) =>
            link.socket?.send({ type: "settings.update", settings })
          }
          onClose={() => setSettingsOpen(false)}
        />
      )}

      {feed.question && (
        <QuestionPrompt
          question={feed.question}
          placement={questionPlacement(avatarFrame, viewport)}
          onAnswer={(answer) => {
            if (feed.question) {
              link.socket?.send({
                type: "question.answer",
                question_id: feed.question.question_id,
                answer,
              });
            }
            feed.dismissQuestion();
          }}
          onDismiss={feed.dismissQuestion}
        />
      )}

      <Toasts toasts={feed.toasts} onDone={feed.dismissToast} />
      <Subtitles line={feed.subtitle} />
      <Pointer command={pointer} home={home} viewport={viewport} />
    </>
  );
}
