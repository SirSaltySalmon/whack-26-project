import { useState } from "react";
import type { KeyName } from "../../../../lib/launcher.ts";
import { logger } from "../../../../lib/logger.ts";
import { Notice, Pill, Section } from "../../components/ui.tsx";
import { useControl } from "../../ControlContext.tsx";

/** What each key turns on, so the demo can show the parts lighting up. */
const UNLOCKS: Record<
  KeyName,
  { label: string; does: string; optional?: boolean }
> = {
  GEMINI_API_KEY: {
    label: "Gemini",
    does: "Replies, tools, pointing at things and session notes. Free tier.",
  },
  ANTHROPIC_API_KEY: {
    label: "Anthropic",
    does: "Watching the screen, and looking closer when you ask. Paid, about 3 cents a minute.",
  },
  DEEPGRAM_API_KEY: {
    label: "Deepgram",
    does: "Hearing you: speech to text with its own turn detection.",
  },
  ELEVENLABS_API_KEY: {
    label: "ElevenLabs",
    does: "Speaking out loud. Needs a voice picked in Voices; without it, replies are subtitles.",
  },
  EXA_API_KEY: {
    label: "Exa",
    does: "Web search when the game's wiki has no answer.",
    optional: true,
  },
  CARTESIA_API_KEY: {
    label: "Cartesia",
    does: "Backup text to speech.",
    optional: true,
  },
};

function KeyRow({ name }: { name: KeyName }) {
  const control = useControl();
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const status = control.keys.keys.find((key) => key.name === name);
  const inEnv = control.description?.keys_set[name] ?? false;
  const info = UNLOCKS[name];

  const run = (work: Promise<void>): void => {
    setBusy(true);
    work
      .then(() => setDraft(""))
      .catch((error: unknown) =>
        logger.error(`Could not update ${name}`, error),
      )
      .finally(() => setBusy(false));
  };

  return (
    <div className="cc-key">
      <div className="cc-key-info">
        <div className="cc-key-title">
          <strong>{info.label}</strong>
          <code>{name}</code>
          {info.optional && <span className="cc-hint">optional</span>}
        </div>
        <p className="cc-hint">{info.does}</p>
      </div>
      <div className="cc-key-state">
        {status?.saved ? (
          <Pill tone="on" title="Encrypted on this computer">
            Saved here {status.hint}
          </Pill>
        ) : inEnv ? (
          <Pill tone="info" title="Read from .env or the environment">
            From .env
          </Pill>
        ) : (
          <Pill tone="off">Missing</Pill>
        )}
      </div>
      <form
        className="cc-key-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (draft.trim()) run(control.setKey(name, draft));
        }}
      >
        <input
          className="cc-input"
          type="password"
          value={draft}
          placeholder={status?.saved ? "Replace key" : "Paste key"}
          autoComplete="off"
          spellCheck={false}
          disabled={busy || !control.keys.canEncrypt}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button
          className="cc-button"
          type="submit"
          disabled={busy || !draft.trim()}
        >
          Save
        </button>
        {status?.saved && (
          <button
            className="cc-button cc-button-quiet"
            type="button"
            disabled={busy}
            onClick={() => run(control.clearKey(name))}
          >
            Remove
          </button>
        )}
      </form>
    </div>
  );
}

export function KeysTab() {
  const control = useControl();
  const names = Object.keys(UNLOCKS) as KeyName[];
  return (
    <div className="cc-page">
      <Section
        title="API keys"
        hint="Encrypted with your Windows account and handed only to the partner's process when it starts. This window never sees a saved key again: just whether it's there."
      >
        {!control.keys.canEncrypt && (
          <Notice tone="warn">
            This computer can't encrypt keys for the app, so they can't be saved
            here. Put them in .env instead.
          </Notice>
        )}
        <div className="cc-keys">
          {names.map((name) => (
            <KeyRow key={name} name={name} />
          ))}
        </div>
        <p className="cc-hint">
          A key saved here wins over the same key in .env. Remove it here to
          fall back to .env.
        </p>
      </Section>
    </div>
  );
}
