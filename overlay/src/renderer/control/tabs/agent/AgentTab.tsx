import { SettingsFields } from "../../../shared/SettingsFields.tsx";
import {
  Field,
  Notice,
  Section,
  TextInput,
  Toggle,
} from "../../components/ui.tsx";
import { useControl } from "../../ControlContext.tsx";

export function AgentTab() {
  const control = useControl();
  const { config, updateConfig, description, describeError, connected } =
    control;
  const live = config.mode === "live";

  return (
    <div className="cc-page">
      <Section
        title="Partner"
        hint={
          connected
            ? "Changes apply right away, like the settings card in the overlay."
            : "Sent to the partner the moment it starts, so its first line already uses them."
        }
      >
        <div className="settings cc-settings">
          <SettingsFields
            choices={control.choices}
            onChange={control.changeSettings}
            allowDefaultVoice
          />
        </div>
      </Section>

      <Section
        title="Game"
        hint="Nothing in the brain is written for one game: these just tell it what to watch and what to file memory under."
      >
        <div className="cc-grid">
          <Field
            label="Game process"
            hint={
              <>
                The window to capture, without .exe. Capture stays off until
                it's set.
                {description?.game_process &&
                  ` .env says ${description.game_process}.`}
              </>
            }
          >
            <TextInput
              value={config.gameProcess}
              placeholder={description?.game_process || "Terraria"}
              onChange={(gameProcess) =>
                updateConfig((c) => ({ ...c, gameProcess }))
              }
            />
          </Field>
          <Field
            label="Game title"
            hint="Memory, the learned profile and the wiki search are all filed under this."
          >
            <TextInput
              value={config.gameTitle}
              // The brain's default title is a fallback, not an example worth showing.
              placeholder="Terraria"
              onChange={(gameTitle) =>
                updateConfig((c) => ({ ...c, gameTitle }))
              }
            />
          </Field>
        </div>
      </Section>

      <Section title="Launch" hint="Applies the next time the partner starts.">
        <div className="settings-row cc-mode">
          <button
            type="button"
            className={`option${live ? " option-on" : ""}`}
            onClick={() => updateConfig((c) => ({ ...c, mode: "live" }))}
          >
            Live game
          </button>
          <button
            type="button"
            className={`option${live ? "" : " option-on"}`}
            onClick={() => updateConfig((c) => ({ ...c, mode: "replay" }))}
          >
            Recorded session
          </button>
        </div>
        {!live && (
          <Field
            label="Session folder"
            hint="A folder under sessions/ made with Record session. Replays spend nothing on vision or speech."
          >
            <TextInput
              value={config.replayDir}
              placeholder="sessions/2026-11-07_2130"
              onChange={(replayDir) =>
                updateConfig((c) => ({ ...c, replayDir }))
              }
            />
          </Field>
        )}
        <div className="cc-toggles">
          <Toggle
            label="Typed turns"
            hint="Talk to the partner from the Console tab, with no microphone."
            on={config.typed}
            onChange={(typed) => updateConfig((c) => ({ ...c, typed }))}
          />
          <Toggle
            label="Record session"
            hint="Saves screen, events and messages for replay. Stores screen data, so it's off by default."
            on={config.record && live}
            disabled={!live}
            onChange={(record) => updateConfig((c) => ({ ...c, record }))}
          />
          <Toggle
            label="Detailed logs"
            hint="Debug and library lines in the Console."
            on={config.verbose}
            onChange={(verbose) => updateConfig((c) => ({ ...c, verbose }))}
          />
        </div>
      </Section>

      <Section
        title="Advanced"
        aside={
          <button
            type="button"
            className="cc-button"
            onClick={control.refreshDescription}
          >
            Check again
          </button>
        }
      >
        {describeError && (
          <Notice tone="warn">
            Couldn't reach the brain's Python: {describeError}. Check the path
            below, then Check again.
          </Notice>
        )}
        <Field
          label="Python"
          hint="Leave empty to use the repo's .venv. The brain starts with: python -m brain"
        >
          <TextInput
            value={config.pythonPath}
            placeholder=".venv\Scripts\python.exe"
            onChange={(pythonPath) =>
              updateConfig((c) => ({ ...c, pythonPath }))
            }
          />
        </Field>
      </Section>
    </div>
  );
}
