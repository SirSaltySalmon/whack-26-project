// Drives the AI Gamer Partner app: the Electron overlay plus its Control Center window, which
// starts and stops the Python brain. Talks to Electron over the Chrome DevTools Protocol, using
// only Node's built-in fetch and WebSocket, so it needs no npm install.
//
// One command per run, so it works from any shell with no tmux:
//   node .claude/skills/run-whack-26-project/driver.mjs <command> [args]
// Run with no command for the list.
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, openSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const ROOT = resolve(import.meta.dirname, "../../..");
const OVERLAY = join(ROOT, "overlay");
const PORT = Number(process.env.CDP_PORT ?? 9223);
const SHOTS = process.env.SCREENSHOT_DIR ?? join(tmpdir(), "partner-shots");
const ELECTRON = join(
  OVERLAY,
  "node_modules/electron/dist",
  process.platform === "win32"
    ? "electron.exe"
    : process.platform === "darwin"
      ? "Electron.app/Contents/MacOS/Electron"
      : "electron",
);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function targets() {
  try {
    return await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
  } catch {
    return null;
  }
}

/** Connects to the page whose URL contains `match` ("control.html" or "index.html"). */
async function page(match = "control.html") {
  const found = (await targets())?.find(
    (t) => t.type === "page" && t.url.includes(match),
  );
  if (!found) throw new Error(`No ${match} page. Run: launch`);
  const socket = new WebSocket(found.webSocketDebuggerUrl);
  const waiting = new Map();
  let next = 0;
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    waiting.get(message.id)?.(message);
    waiting.delete(message.id);
  };
  await new Promise((ok, fail) => {
    socket.onopen = ok;
    socket.onerror = () => fail(new Error("Could not attach to the page"));
  });
  const call = (method, params = {}) =>
    new Promise((ok) => {
      next += 1;
      waiting.set(next, ok);
      socket.send(JSON.stringify({ id: next, method, params }));
    });
  const evaluate = async (expression) => {
    const reply = await call("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    const error = reply.result?.exceptionDetails;
    if (error) throw new Error(error.exception?.description ?? error.text);
    return reply.result?.result?.value;
  };
  // Wait for the close to finish: exiting while it's in flight trips a libuv assertion on
  // Windows (UV_HANDLE_CLOSING) and kills Node with exit code 127.
  const close = () =>
    new Promise((done) => {
      const timer = setTimeout(done, 1000);
      socket.onclose = () => {
        clearTimeout(timer);
        done();
      };
      socket.close();
    });
  return { call, evaluate, close };
}

async function inPage(expression, match) {
  const p = await page(match);
  try {
    return await p.evaluate(expression);
  } finally {
    await p.close();
  }
}

// React keeps its own copy of an input's value, so setting .value alone is ignored: use the
// native setter, then fire the input event React listens for.
const FILL = `(el, value) => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
}`;
const CLICK_TEXT = `(text) => {
  const els = [...document.querySelectorAll('button, label, summary')];
  const el = els.find(e => e.textContent.trim() === text) ?? els.find(e => e.textContent.includes(text));
  if (!el) return 'NOT_FOUND: ' + text;
  el.click();
  return 'clicked ' + el.tagName.toLowerCase() + ': ' + el.textContent.trim().slice(0, 40);
}`;
const STATE = `document.querySelector('.cc-run .cc-pill')?.textContent ?? 'not loaded'`;

async function waitFor(expression, test, timeoutMs, what) {
  const deadline = Date.now() + timeoutMs;
  let last;
  while (Date.now() < deadline) {
    try {
      last = await inPage(expression);
      if (test(last)) return last;
    } catch {
      // The page may still be loading.
    }
    await sleep(500);
  }
  throw new Error(
    `Timed out waiting for ${what} (last: ${JSON.stringify(last)})`,
  );
}

const json = (value) => JSON.stringify(value);

const COMMANDS = {
  async launch() {
    if (await targets()) return console.log(`already running on port ${PORT}`);
    if (!existsSync(join(OVERLAY, "out/main/index.js"))) {
      throw new Error("No build. Run: npm --prefix overlay run build");
    }
    mkdirSync(SHOTS, { recursive: true });
    const log = join(SHOTS, "electron.log");
    const env = { ...process.env };
    // Set by shells that VS Code extensions start; it makes Electron run as plain Node.
    delete env.ELECTRON_RUN_AS_NODE;
    const out = openSync(log, "w");
    spawn(ELECTRON, [`--remote-debugging-port=${PORT}`, OVERLAY], {
      cwd: OVERLAY,
      env,
      detached: true,
      stdio: ["ignore", out, out],
    }).unref();
    await waitFor(
      `!!document.querySelector('.cc-run')`,
      Boolean,
      30000,
      "the Control Center",
    );
    console.log(`launched; Electron log: ${log}`);
    await COMMANDS.pages();
  },

  async pages() {
    for (const t of (await targets()) ?? []) console.log(t.type, t.url);
  },

  /** ss [name] [overlay]: the Control Center, or the transparent overlay window. */
  async ss(name = `ss-${Date.now()}`, which = "control") {
    mkdirSync(SHOTS, { recursive: true });
    const p = await page(which === "overlay" ? "index.html" : "control.html");
    const shot = await p.call("Page.captureScreenshot", { format: "png" });
    await p.close();
    const file = join(SHOTS, `${name}.png`);
    writeFileSync(file, Buffer.from(shot.result.data, "base64"));
    console.log(`screenshot: ${file}`);
  },

  async tab(title) {
    console.log(
      await inPage(`(() => {
        const tab = [...document.querySelectorAll('.cc-tab')].find(b => b.textContent.includes(${json(title)}));
        if (!tab) return 'NOT_FOUND: ' + ${json(title)};
        tab.click();
        return 'tab: ' + tab.textContent.trim();
      })()`),
    );
    await sleep(400);
  },

  async click(text) {
    console.log(await inPage(`(${CLICK_TEXT})(${json(text)})`));
  },

  async "click-css"(selector) {
    console.log(
      await inPage(`(() => {
        const el = document.querySelector(${json(selector)});
        if (!el) return 'NOT_FOUND';
        el.click();
        return 'clicked';
      })()`),
    );
  },

  /** field <label> <value>: a text field, found by the label above it. */
  async field(label, value = "") {
    console.log(
      await inPage(`(() => {
        const field = [...document.querySelectorAll('.cc-field')].find(f => f.querySelector('.cc-field-label')?.textContent === ${json(label)});
        const input = field?.querySelector('input');
        if (!input) return 'NOT_FOUND: ' + ${json(label)} + ' (open its tab first, e.g. tab Agent)';
        (${FILL})(input, ${json(value)});
        return 'filled ' + ${json(label)};
      })()`),
    );
  },

  /** fill <css> <value>: any input, then optionally submit its form with `submit <css>`. */
  async fill(selector, value = "") {
    console.log(
      await inPage(`(() => {
        const input = document.querySelector(${json(selector)});
        if (!input) return 'NOT_FOUND';
        (${FILL})(input, ${json(value)});
        return 'filled';
      })()`),
    );
  },

  async submit(selector) {
    console.log(
      await inPage(`(() => {
        const form = document.querySelector(${json(selector)})?.closest('form');
        if (!form) return 'NOT_FOUND';
        form.requestSubmit();
        return 'submitted';
      })()`),
    );
  },

  async start() {
    console.log(await inPage(`(${CLICK_TEXT})('Start partner')`));
    const state = await waitFor(
      STATE,
      (s) => /^Running$|Stopped/.test(s),
      60000,
      "the brain",
    );
    console.log(`state: ${state}`);
  },

  async stop() {
    console.log(await inPage(`(${CLICK_TEXT})('Stop')`));
    const state = await waitFor(
      STATE,
      (s) => /Not running|Stopped/.test(s),
      30000,
      "the stop",
    );
    console.log(`state: ${state}`);
  },

  async state() {
    console.log(
      await inPage(`[${STATE}, ...[...document.querySelectorAll('.cc-capabilities .cc-pill')]
        .map(p => p.textContent + (p.classList.contains('cc-pill-on') ? ' on' : ' off'))].join(' | ')`),
    );
  },

  /** turn <text>: a player turn, as if spoken. Needs "Typed turns" on and the brain running. */
  async turn(text) {
    await inPage(`window.control.typeTurn(${json(text)})`);
    console.log("sent");
  },

  /** logs [n]: the brain's last n log lines, whichever tab is open. */
  async logs(n = "30") {
    const lines = await inPage(`window.control.getLogs()`);
    console.log(lines.slice(-Number(n)).join("\n"));
  },

  async text(selector) {
    console.log(
      await inPage(
        selector
          ? `document.querySelector(${json(selector)})?.innerText ?? '(not found)'`
          : `document.querySelector('.cc-main').innerText`,
      ),
    );
  },

  async eval(expression) {
    console.log(json(await inPage(expression)));
  },

  /** wait <css>: until the element exists, up to 10 s. Tabs render a moment after `tab`. */
  async wait(selector) {
    await waitFor(
      `!!document.querySelector(${json(selector)})`,
      Boolean,
      10000,
      selector,
    );
    console.log(`found ${selector}`);
  },

  /** Closes the Control Center, which stops the brain cleanly and quits the app. */
  async quit() {
    if (!(await targets())) return console.log("not running");
    await inPage(`setTimeout(() => window.close(), 50), 'closing'`);
    for (let i = 0; i < 60 && (await targets()); i += 1) await sleep(500);
    console.log((await targets()) ? "still running after 30 s" : "quit");
  },
};

// Never process.exit(): forcing an exit while fetch or WebSocket handles are still closing trips
// the same libuv assertion. Every handle here is closed or unref'd, so Node exits by itself.
const [command, ...args] = process.argv.slice(2);
const run = COMMANDS[command];
if (!run) {
  console.log(`commands: ${Object.keys(COMMANDS).join(", ")}`);
  process.exitCode = command ? 1 : 0;
} else {
  try {
    await run(...args);
  } catch (error) {
    console.log(`ERROR: ${error.message}`);
    process.exitCode = 1;
  }
}
