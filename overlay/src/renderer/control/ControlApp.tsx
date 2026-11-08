import { useState } from "react";
import { logger } from "../../lib/logger.ts";
import { Header } from "./components/Header.tsx";
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

export function ControlApp() {
  const control = useControl();
  const [activeId, setActiveId] = useState(
    () => pickTab(TABS, rememberedTab())?.id,
  );
  const active = pickTab(TABS, activeId ?? null);

  const open = (id: string): void => {
    setActiveId(id);
    remember(id);
  };

  return (
    <div className="cc-app">
      <Header />
      <nav className="cc-nav" aria-label="Tabs">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`cc-tab${tab.id === active?.id ? " cc-tab-on" : ""}`}
            aria-current={tab.id === active?.id ? "page" : undefined}
            onClick={() => open(tab.id)}
          >
            <span className="cc-tab-icon" aria-hidden>
              {tab.icon}
            </span>
            {tab.title}
            {tab.needsBrain && !control.connected && (
              <span className="cc-tab-dot" title="Needs the partner running" />
            )}
          </button>
        ))}
      </nav>
      <main className="cc-main">
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
            <h2>{active.title} needs the partner running</h2>
            <p className="cc-hint">
              Press Start partner at the top right. It connects in a few
              seconds.
            </p>
          </div>
        ) : (
          <active.Component key={active.id} />
        )}
      </main>
    </div>
  );
}
