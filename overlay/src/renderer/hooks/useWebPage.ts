import type { WebviewTag } from "electron";
import { useCallback, useEffect, useRef, useState } from "react";
import { logger } from "../../lib/logger.ts";

// Chromium's "aborted": a new navigation replaced this one, which isn't a failure.
const ERR_ABORTED = -3;

export interface WebPageView {
  ref: (element: WebviewTag | null) => void;
  /** Set once. Later pages load through the webview, so React never reassigns `src` and reloads. */
  initialUrl: string;
  canGoBack: boolean;
  canGoForward: boolean;
  loading: boolean;
  failed: boolean;
  goBack(): void;
  goForward(): void;
  reload(): void;
  focus(): void;
}

interface Options {
  requestedUrl: string;
  requestSeq: number;
  onNavigated(url: string, title?: string): void;
}

export function useWebPage({
  requestedUrl,
  requestSeq,
  onNavigated,
}: Options): WebPageView {
  const [initialUrl] = useState(requestedUrl);
  const [element, setElement] = useState<WebviewTag | null>(null);
  const [ready, setReady] = useState(false);
  const [canGoBack, setCanGoBack] = useState(false);
  const [canGoForward, setCanGoForward] = useState(false);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const attempted = useRef(requestedUrl);
  const handledSeq = useRef(requestSeq);
  const navigated = useRef(onNavigated);
  navigated.current = onNavigated;

  const load = useCallback((view: WebviewTag, url: string): void => {
    attempted.current = url;
    view.loadURL(url).catch((error: unknown) => {
      // Chromium also rejects this for a navigation that got replaced, so did-fail-load decides.
      logger.debug(`Load interrupted: ${url}`, error);
    });
  }, []);

  useEffect(() => {
    if (!element) return;
    const syncHistory = (): void => {
      setCanGoBack(element.canGoBack());
      setCanGoForward(element.canGoForward());
    };
    const onReady = (): void => {
      setReady(true);
      syncHistory();
    };
    const onStart = (): void => {
      setLoading(true);
      setFailed(false);
    };
    const onStop = (): void => {
      setLoading(false);
      syncHistory();
    };
    const onFail = (event: Electron.DidFailLoadEvent): void => {
      if (!event.isMainFrame || event.errorCode === ERR_ABORTED) return;
      logger.warn(
        `Page failed to load (${event.errorDescription}): ${event.validatedURL}`,
      );
      attempted.current = event.validatedURL || attempted.current;
      setFailed(true);
    };
    const onNavigate = (event: Electron.DidNavigateEvent): void => {
      navigated.current(event.url);
      syncHistory();
    };
    const onNavigateInPage = (event: Electron.DidNavigateInPageEvent): void => {
      if (!event.isMainFrame) return;
      navigated.current(event.url);
      syncHistory();
    };
    const onTitle = (event: Electron.PageTitleUpdatedEvent): void => {
      navigated.current(element.getURL(), event.title);
    };

    element.addEventListener("dom-ready", onReady);
    element.addEventListener("did-start-loading", onStart);
    element.addEventListener("did-stop-loading", onStop);
    element.addEventListener("did-fail-load", onFail);
    element.addEventListener("did-navigate", onNavigate);
    element.addEventListener("did-navigate-in-page", onNavigateInPage);
    element.addEventListener("page-title-updated", onTitle);
    return () => {
      element.removeEventListener("dom-ready", onReady);
      element.removeEventListener("did-start-loading", onStart);
      element.removeEventListener("did-stop-loading", onStop);
      element.removeEventListener("did-fail-load", onFail);
      element.removeEventListener("did-navigate", onNavigate);
      element.removeEventListener("did-navigate-in-page", onNavigateInPage);
      element.removeEventListener("page-title-updated", onTitle);
    };
  }, [element]);

  // The webview throws if asked to navigate before dom-ready, so a request waits until then.
  useEffect(() => {
    if (element && ready && handledSeq.current !== requestSeq) {
      handledSeq.current = requestSeq;
      load(element, requestedUrl);
    }
  }, [element, ready, requestSeq, requestedUrl, load]);

  return {
    ref: setElement,
    initialUrl,
    canGoBack,
    canGoForward,
    loading,
    failed,
    goBack: () => element?.goBack(),
    goForward: () => element?.goForward(),
    // A failed load has nothing committed to reload, so retry what was asked for.
    reload: () => {
      if (!element || !ready) return;
      if (failed) {
        load(element, attempted.current);
      } else {
        element.reload();
      }
    },
    focus: () => element?.focus(),
  };
}
