import type { Skin } from "../hooks/useSkin.ts";
import { SKINS } from "../logic/skins.ts";

/**
 * Buttons only, so picking a look in the overlay never takes the keyboard from the game. Shared by
 * the overlay's settings card and the Control Center's Avatar tab.
 */
export function SkinPicker({ skin }: { skin: Skin }) {
  const chosen = SKINS.find((option) => option.id === skin.skin);
  return (
    <>
      <div className="settings-row">
        {SKINS.map((option) => (
          <button
            key={option.id}
            className={`option${skin.skin === option.id ? " option-on" : ""}`}
            type="button"
            aria-pressed={skin.skin === option.id}
            title={option.hint}
            onClick={() => skin.choose(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>
      {/* Each window styles its own hint class. */}
      <p className="settings-hint cc-hint">{chosen?.hint}</p>
    </>
  );
}
