import { useState } from "react";
import {
  Field,
  Notice,
  Pill,
  Section,
  TextInput,
  Toggle,
} from "../../components/ui.tsx";
import { useControl } from "../../ControlContext.tsx";
import { Keyterms } from "./Keyterms.tsx";

const SAMPLE = "Hey! This is how I'll sound while you play.";

/** A blank field means the system default device. */
function deviceIndex(text: string): number | null {
  const value = Number.parseInt(text, 10);
  return Number.isInteger(value) && value >= 0 ? value : null;
}

export function VoicesTab() {
  const control = useControl();
  const { config, updateConfig, connected, status } = control;
  const chosen = control.choices.settings.voice_id ?? null;
  const fromEnv = new Set(
    (control.description?.voices ?? []).map((voice) => voice.id),
  );
  const [name, setName] = useState("");
  const [id, setId] = useState("");
  const [sample, setSample] = useState(SAMPLE);

  const pick = (voiceId: string): void =>
    control.changeSettings({ ...control.choices.settings, voice_id: voiceId });

  const add = (): void => {
    const voice = { name: name.trim(), id: id.trim() };
    if (!voice.name || !voice.id) return;
    updateConfig((c) => ({
      ...c,
      customVoices: [...c.customVoices.filter((v) => v.id !== voice.id), voice],
    }));
    setName("");
    setId("");
  };

  return (
    <div className="cc-page">
      <Section
        title="Voice"
        hint="ElevenLabs voices. Picking one applies right away while the partner runs."
      >
        {control.voices.length === 0 && (
          <p className="cc-hint">
            No voices yet: add one below, or list them in VOICE_OPTIONS in .env.
            Until then the partner uses ELEVENLABS_VOICE_ID.
          </p>
        )}
        <div className="voice-list">
          {control.voices.map((voice) => (
            <label
              key={voice.id}
              className={`voice-row${chosen === voice.id ? " voice-row-on" : ""}`}
            >
              <input
                type="radio"
                checked={chosen === voice.id}
                onChange={() => pick(voice.id)}
              />
              <span className="voice-name">{voice.name}</span>
              <code className="cc-hint">{voice.id}</code>
              {fromEnv.has(voice.id) ? (
                <Pill tone="info">.env</Pill>
              ) : (
                <button
                  type="button"
                  className="cc-button cc-button-quiet"
                  onClick={() =>
                    updateConfig((c) => ({
                      ...c,
                      customVoices: c.customVoices.filter(
                        (v) => v.id !== voice.id,
                      ),
                    }))
                  }
                >
                  Remove
                </button>
              )}
            </label>
          ))}
        </div>
        <form
          className="voice-add"
          onSubmit={(event) => {
            event.preventDefault();
            add();
          }}
        >
          <TextInput value={name} placeholder="Name" onChange={setName} />
          <TextInput
            value={id}
            placeholder="ElevenLabs voice ID"
            onChange={setId}
          />
          <button
            className="cc-button"
            type="submit"
            disabled={!name.trim() || !id.trim()}
          >
            Add voice
          </button>
        </form>
        <p className="cc-hint">
          New voices reach the in-game settings card on the next start.
        </p>
      </Section>

      <Section
        title="Preview"
        hint="Says a line in the chosen voice, unless the partner is already talking."
      >
        <div className="voice-preview">
          <TextInput value={sample} onChange={setSample} />
          <button
            className="cc-button cc-button-primary"
            type="button"
            disabled={!connected || !sample.trim()}
            onClick={() =>
              control.send({
                type: "voice.preview",
                text: sample.trim().slice(0, 200),
              })
            }
          >
            Say it
          </button>
        </div>
        {connected && status && !status.speaking && (
          <Notice>
            The partner is replying in subtitles: the preview shows as a
            subtitle. Speech needs the Deepgram and ElevenLabs keys and a voice.
          </Notice>
        )}
        {!connected && (
          <p className="cc-hint">Start the partner to hear a preview.</p>
        )}
      </Section>

      <Section
        title="Listening"
        hint="Applies the next time the partner starts."
      >
        <Toggle
          label="No headphones"
          hint="Mutes the mic while the partner talks, so it can't hear itself. You lose barge-in."
          on={config.tuning.halfDuplex}
          onChange={(halfDuplex) =>
            updateConfig((c) => ({ ...c, tuning: { ...c.tuning, halfDuplex } }))
          }
        />
        <Field
          label="Words to listen for"
          hint="Boss, item and place names that speech to text should get right."
        >
          <Keyterms
            terms={config.tuning.keyterms}
            onChange={(keyterms) =>
              updateConfig((c) => ({ ...c, tuning: { ...c.tuning, keyterms } }))
            }
          />
        </Field>
        <div className="cc-grid">
          <Field
            label="Microphone device"
            hint="PyAudio index. Empty uses the default."
          >
            <TextInput
              type="number"
              value={config.tuning.micIndex?.toString() ?? ""}
              onChange={(text) =>
                updateConfig((c) => ({
                  ...c,
                  tuning: { ...c.tuning, micIndex: deviceIndex(text) },
                }))
              }
            />
          </Field>
          <Field
            label="Speaker device"
            hint="PyAudio index. Empty uses the default."
          >
            <TextInput
              type="number"
              value={config.tuning.speakerIndex?.toString() ?? ""}
              onChange={(text) =>
                updateConfig((c) => ({
                  ...c,
                  tuning: { ...c.tuning, speakerIndex: deviceIndex(text) },
                }))
              }
            />
          </Field>
        </div>
      </Section>
    </div>
  );
}
