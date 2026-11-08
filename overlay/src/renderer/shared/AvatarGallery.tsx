import { useRef } from "react";
import catUrl from "../assets/avatar-cat.png";
import type { Avatars } from "../hooks/useAvatars.ts";
import { BUILT_IN_AVATARS, CAT_ID } from "../logic/avatars.ts";
import "./avatars.css";

interface Tile {
  id: string;
  name: string;
  /** Null draws the plain circle. */
  src: string | null;
}

const ACCEPTED = "image/png,image/jpeg,image/webp,image/gif,image/bmp";

/**
 * Every avatar as a button showing its picture, then a tile to upload another. Buttons only, so
 * picking one in the overlay never takes the keyboard from the game. Uploading opens the system
 * file dialog, which does take it until it closes: that's the player's choice.
 */
export function AvatarGallery({
  avatars,
  large = false,
}: {
  avatars: Avatars;
  large?: boolean;
}) {
  const picker = useRef<HTMLInputElement>(null);
  const tiles: Tile[] = [
    ...BUILT_IN_AVATARS.map((avatar) => ({
      ...avatar,
      src: avatar.id === CAT_ID ? catUrl : null,
    })),
    ...(avatars.uploads ?? []).map((avatar) => ({
      id: avatar.id,
      name: avatar.name,
      src: avatar.image,
    })),
  ];

  return (
    <div className={`avatar-gallery${large ? " avatar-gallery-large" : ""}`}>
      {tiles.map((tile) => {
        const on = tile.id === avatars.choice;
        return (
          <button
            key={tile.id}
            className={`avatar-tile${on ? " avatar-tile-on" : ""}`}
            type="button"
            aria-pressed={on}
            title={tile.name}
            onClick={() => avatars.choose(tile.id)}
          >
            <span className="avatar-tile-art">
              {tile.src === null ? (
                <span className="avatar-tile-circle" />
              ) : (
                <img src={tile.src} alt="" draggable={false} />
              )}
            </span>
            <span className="avatar-tile-name">{tile.name}</span>
          </button>
        );
      })}
      <button
        className="avatar-tile avatar-tile-add"
        type="button"
        title="Upload an image"
        disabled={avatars.busy}
        onClick={() => picker.current?.click()}
      >
        <span className="avatar-tile-art" aria-hidden>
          {avatars.busy ? "…" : "+"}
        </span>
        <span className="avatar-tile-name">
          {avatars.busy ? "Preparing" : "Upload"}
        </span>
      </button>
      <input
        ref={picker}
        type="file"
        accept={ACCEPTED}
        hidden
        onChange={(event) => {
          const file = event.currentTarget.files?.[0];
          // Cleared so picking the same file again still counts as a change.
          event.currentTarget.value = "";
          if (file) avatars.upload(file);
        }}
      />
    </div>
  );
}
