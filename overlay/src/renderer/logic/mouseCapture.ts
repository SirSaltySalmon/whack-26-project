/**
 * Decides when the overlay catches the mouse. Capture stays on through a whole drag even if the
 * cursor outruns the handle, or the release would land on the game and the drag would stick.
 */
export class MouseCapture {
  private readonly apply: (capture: boolean) => void;
  private over = false;
  private gesturing = false;
  private applied = false;

  constructor(apply: (capture: boolean) => void) {
    this.apply = apply;
  }

  hover(overInteractive: boolean): void {
    this.over = overInteractive;
    this.sync();
  }

  beginGesture(): void {
    this.gesturing = true;
    this.sync();
  }

  /** Pass where the cursor ended up, since it may have left the handle during the drag. */
  endGesture(overInteractive: boolean): void {
    this.gesturing = false;
    this.over = overInteractive;
    this.sync();
  }

  get isGesturing(): boolean {
    return this.gesturing;
  }

  private sync(): void {
    const capture = this.over || this.gesturing;
    if (capture !== this.applied) {
      this.applied = capture;
      this.apply(capture);
    }
  }
}
