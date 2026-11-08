import {
  fullPacing,
  PACING_MAX,
  PACING_PRESETS,
  samePacing,
  type FullPacing,
  type PacingKey,
} from "../../../../lib/pacing.ts";
import { Choice } from "../../../shared/SettingsFields.tsx";
import { Field, Notice, Section } from "../../components/ui.tsx";
import { useControl } from "../../ControlContext.tsx";
import { SecondsInput } from "./SecondsInput.tsx";

interface PacingField {
  key: PacingKey;
  label: string;
  hint: string;
}

interface PacingGroup {
  title: string;
  hint: string;
  fields: PacingField[];
}

const GROUPS: readonly PacingGroup[] = [
  {
    title: "Game events",
    hint: "Comments on what happens in the game, like getting hit or a boss showing up.",
    fields: [
      {
        key: "event_gap_s",
        label: "Between reactions",
        hint: "The least time from one reaction to the next. Events in between pass without a word.",
      },
    ],
  },
  {
    title: "Questions",
    hint: "Spoken questions about you and your game, asked when memory doesn't know.",
    fields: [
      {
        key: "question_gap_s",
        label: "Between questions",
        hint: "The cooldown from one question to the next. The first can come as soon as the partner connects.",
      },
      {
        key: "question_quiet_s",
        label: "Quiet before asking",
        hint: "Since you or the partner last spoke. 0 asks as soon as the gap is up, though never over the partner, mid-sentence or in danger.",
      },
    ],
  },
  {
    title: "Tips",
    hint: "What to try next, given unasked. Only with Offer hints on.",
    fields: [
      {
        key: "advice_first_s",
        label: "First tip",
        hint: "After the overlay connects.",
      },
      {
        key: "advice_gap_s",
        label: "Between tips",
        hint: "0 turns tips off.",
      },
      {
        key: "advice_quiet_s",
        label: "Quiet before a tip",
        hint: "Since anyone spoke, and since the last question.",
      },
    ],
  },
];

export function PacingTab() {
  const control = useControl();
  const { settings } = control.choices;
  const pacing = fullPacing(settings.pacing);
  const hintsOff = settings.proactive === false;

  const change = (next: FullPacing) =>
    control.changeSettings({ ...settings, pacing: next });

  return (
    <div className="cc-page">
      <Section
        title="Pacing"
        hint={
          control.connected
            ? "How often the partner speaks up unasked, in seconds. Changes apply right away."
            : "How often the partner speaks up unasked, in seconds. Sent to the partner the moment it starts."
        }
      >
        <div className="settings-row">
          {PACING_PRESETS.map((preset) => (
            <Choice
              key={preset.name}
              label={preset.name}
              on={samePacing(pacing, preset.pacing)}
              onClick={() => change(preset.pacing)}
            />
          ))}
        </div>
        <p className="cc-hint">
          Lively brings questions and tips sooner, for a short demo. Calm is the
          pacing from before this tab. Replies to you are never held back by any
          of these.
        </p>
      </Section>

      {GROUPS.map((group) => (
        <Section key={group.title} title={group.title} hint={group.hint}>
          {group.title === "Tips" && hintsOff && (
            <Notice tone="warn">
              Hints are off in the Agent tab, so no tips are given.
            </Notice>
          )}
          <div className="cc-grid">
            {group.fields.map((field) => (
              <Field key={field.key} label={field.label} hint={field.hint}>
                <SecondsInput
                  name={field.key}
                  value={pacing[field.key]}
                  max={PACING_MAX[field.key]}
                  onCommit={(value) =>
                    change({ ...pacing, [field.key]: value })
                  }
                />
              </Field>
            ))}
          </div>
        </Section>
      ))}
    </div>
  );
}
