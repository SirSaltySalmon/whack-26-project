import type { GameView } from "../../../../lib/protocol.generated.ts";
import { ago } from "../../logic/memory.ts";

const plural = (n: number, noun: string): string =>
  `${n} ${noun}${n === 1 ? "" : "s"}`;

/** GAME_TITLE can be blank, which files every game under an empty title. */
const nameOf = (title: string): string => title || "(untitled)";

function describe(game: GameView, playing: boolean): string {
  const parts = [nameOf(game.title), plural(game.facts, "fact")];
  if (playing) parts.push("playing now");
  return parts.join(" · ");
}

function detail(game: GameView): string {
  const played = game.last_played
    ? `last played ${ago(game.last_played)}`
    : "never played";
  return `${plural(game.sessions, "session")}, ${plural(game.questions, "open question")}, ${played}`;
}

export function GamePicker({
  games,
  value,
  playing,
  onChange,
}: {
  games: readonly GameView[];
  value: string | null;
  /** The game the running partner is filing memory under, if it's running. */
  playing: string | null;
  onChange(title: string): void;
}) {
  if (value === null) {
    return (
      <select className="cc-input mem-game" disabled aria-label="Game">
        <option>No games yet</option>
      </select>
    );
  }
  const picked = games.find((game) => game.title === value);
  return (
    <select
      className="cc-input mem-game"
      aria-label="Game"
      value={value}
      title={picked ? detail(picked) : undefined}
      onChange={(event) => onChange(event.target.value)}
    >
      {!picked && <option value={value}>{nameOf(value)}</option>}
      {games.map((game) => (
        <option key={game.title} value={game.title} title={detail(game)}>
          {describe(game, game.title === playing)}
        </option>
      ))}
    </select>
  );
}
