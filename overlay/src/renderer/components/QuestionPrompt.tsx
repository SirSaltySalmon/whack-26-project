import type { QuestionAsk } from "../../lib/protocol.generated.ts";
import type { QuestionPlacement } from "../logic/layout.ts";

interface QuestionPromptProps {
  question: QuestionAsk;
  placement: QuestionPlacement;
  onAnswer(answer: string): void;
  onDismiss(): void;
}

/**
 * Only the buttons catch clicks, because the game aims with the mouse. There's no text box, so the
 * overlay never takes the keyboard from the game: an open question is answered out loud.
 */
export function QuestionPrompt({
  question,
  placement,
  onAnswer,
  onDismiss,
}: QuestionPromptProps) {
  const options = question.options ?? [];
  return (
    <div className="question" data-rect-id="question" style={placement}>
      <p className="question-text">{question.text}</p>
      <div className="question-options">
        {options.map((option) => (
          <button
            key={option}
            className="option"
            data-interactive
            type="button"
            onClick={() => onAnswer(option)}
          >
            {option}
          </button>
        ))}
        {options.length === 0 && (
          <span className="question-hint">Just say it out loud.</span>
        )}
        <button
          className="option option-quiet"
          data-interactive
          type="button"
          onClick={onDismiss}
        >
          Not now
        </button>
      </div>
    </div>
  );
}
