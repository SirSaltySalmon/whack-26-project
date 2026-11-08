import { useCallback, useEffect, useState } from "react";
import { logger } from "../../lib/logger.ts";
import { Header, RunControls } from "./components/Header.tsx";
import { Notice } from "./components/ui.tsx";
import { useControl } from "./ControlContext.tsx";
import { pickTab } from "./logic/tabs.ts";
import { TABS } from "./tabs/registry.ts";

const TAB_KEY = "control.tab";

/** Only a convenience, so a failure just opens the first tab. */
function rememberedTab(): string | null {
  try {
    return localStorage.getItem(TAB_KEY);
  } catch (error) {
    logger.warn("Could not read the last tab", error);
    return null;
  }
}

function remember(id: string): void {
  try {
    localStorage.setItem(TAB_KEY, id);
  } catch (error) {
    logger.warn("Could not save the last tab", error);
  }
}

/** Alt+1 to Alt+9 open the tabs in sidebar order; the sidebar shows each one. */
const shortcutFor = (index: number): string | undefined =>
  index < 9 ? `Alt+${index + 1}` : undefined;

export function ControlApp() {
  const control = useControl();
  const [activeId, setActiveId] = useState(
    () => pickTab(TABS, rememberedTab())?.id,
  );
  const active = pickTab(TABS, activeId ?? null);

  const open = useCallback((id: string): void => {
    setActiveId(id);
    remember(id);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey)
        return;
      // A field keeps every key it's given, so typing is never cut short by a tab change.
      const target = event.target;
      if (
        target instanceof Element &&
        target.closest("input, textarea, select")
      )
        return;
      // The key's position, not its character, so the digit row works on every layout.
      const digit = /^Digit([1-9])$/.exec(event.code);
      const tab = digit ? TABS[Number(digit[1]) - 1] : undefined;
      if (!tab) return;
      event.preventDefault();
      open(tab.id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="cc-app">
      <aside className="cc-side">
        <Header />
        <nav className="cc-nav" aria-label="Tabs">
          {TABS.map((tab, index) => {
            const on = tab.id === active?.id;
            const shortcut = shortcutFor(index);
            return (
              <button
                key={tab.id}
                type="button"
                className={`cc-tab${on ? " cc-tab-on" : ""}`}
                aria-current={on ? "page" : undefined}
                aria-keyshortcuts={shortcut}
                onClick={() => open(tab.id)}
              >
                <span className="cc-tab-icon" aria-hidden>
                  {tab.icon}
                </span>
                {tab.title}
                {tab.needsBrain && !control.connected && (
                  <span
                    className="cc-tab-dot"
                    title="Needs the partner running"
                  />
                )}
                {shortcut && <kbd aria-hidden>{shortcut}</kbd>}
              </button>
            );
          })}
        </nav>
        <RunControls />
      </aside>
      <main className="cc-main">
        {active && (
          <header className="cc-main-head">
            <span className="cc-main-icon" aria-hidden>
              {active.icon}
            </span>
            <h2>{active.title}</h2>
          </header>
        )}
        <div className="cc-body">
          {control.restartNeeded && (
            <Notice tone="warn">
              Keys or launch options changed since the partner started. Stop and
              start it to use them.
            </Notice>
          )}
          {active === undefined ? (
            <p className="cc-hint">No tabs found.</p>
          ) : active.needsBrain && !control.connected ? (
            <div className="cc-empty">
              <span className="cc-empty-icon" aria-hidden>
                {active.icon}
              </span>
              <h2>{active.title} needs the partner running</h2>
              <p className="cc-hint">
                Press Start partner. It connects in a few seconds.
              </p>
            </div>
          ) : (
            <active.Component key={active.id} />
          )}
        </div>
      </main>
    </div>
  );
}
