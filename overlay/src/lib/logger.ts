/* The one place the overlay writes logs, in every process. Main-process output goes to the
   terminal, and the main process forwards renderer warnings and errors there too. */
const write =
  (level: "debug" | "info" | "warn" | "error") =>
  (message: string, ...details: unknown[]): void => {
    console[level](`[overlay] ${message}`, ...details);
  };

export const logger = {
  debug: write("debug"),
  info: write("info"),
  warn: write("warn"),
  error: write("error"),
};
