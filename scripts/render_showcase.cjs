/** Render the real overlay over a supplied screenshot using a scripted local server.
 * Usage: overlay/node_modules/electron/dist/electron.exe scripts/render_showcase.cjs <png>
 * No brain startup, AI calls, desktop capture, or changes to the normal app's settings.
 */
const { app, BrowserWindow, session } = require('electron');
const { spawn } = require('node:child_process');
const { readFileSync, mkdirSync, writeFileSync } = require('node:fs');
const { resolve, join } = require('node:path');
const net = require('node:net');

const root = resolve(__dirname, '..');
const input = resolve(process.argv[2] || '');
const mode = process.argv[3] || 'base';
const output = join(root, 'docs/images');
const profile = join(root, 'data/showcase-electron');
mkdirSync(profile, { recursive: true });
app.setPath('userData', profile);
app.commandLine.appendSwitch('force-device-scale-factor', '1');
app.commandLine.appendSwitch('disable-gpu');
let server;
let window;
const delay = (ms) => new Promise((done) => setTimeout(done, ms));

async function portFree() {
  await new Promise((ok, fail) => {
    const probe = net.createServer();
    probe.once('error', () => fail(new Error('Port 8765 is occupied; stop that server first.')));
    probe.listen(8765, '127.0.0.1', () => probe.close(ok));
  });
}

async function waitFor(test, description) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await test()) return;
    await delay(150);
  }
  throw new Error(`Timed out: ${description}`);
}

async function health() {
  try { return await (await fetch('http://127.0.0.1:8765/showcase/health')).json(); }
  catch { return null; }
}

async function run() {
  const background = 'data:image/png;base64,' + readFileSync(input).toString('base64');
  await portFree();
  server = spawn(join(root, '.venv/Scripts/python.exe'), ['-m', 'scripts.showcase_server'], {
    cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  });
  server.stdout.on('data', (chunk) => process.stdout.write(chunk));
  server.stderr.on('data', (chunk) => process.stderr.write(chunk));
  await waitFor(async () => (await health())?.showcase, 'local showcase server');
  const wiki = session.fromPartition('wiki');
  wiki.setPermissionRequestHandler((_contents, _permission, reply) => reply(false));
  wiki.setPermissionCheckHandler(() => false);
  wiki.on('will-download', (event) => event.preventDefault());
  app.on('web-contents-created', (_event, contents) => {
    contents.setWindowOpenHandler(() => ({action:'deny'}));
    contents.on('will-attach-webview', (event, preferences, params) => {
      if (params.partition !== 'wiki' || !/^https?:\/\//.test(params.src)) {
        event.preventDefault(); return;
      }
      delete preferences.preload;
      preferences.nodeIntegration = false;
      preferences.contextIsolation = true;
      preferences.sandbox = true;
    });
  });
  window = new BrowserWindow({
    width: 1920, height: 1080, useContentSize: true, show: false, frame: false,
    webPreferences: {
      preload: join(root, 'overlay/out/preload/index.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: true,
      offscreen: true, backgroundThrottling: false, webviewTag: true,
    },
  });
  window.webContents.on('console-message', (_event, details) => {
    if (details.level === 'error') console.error(details.message);
  });
  // Initial bounds are clamped to the work area; explicitly resize after creation.
  window.setContentSize(1920, 1080);
  console.log('Render bounds', window.getContentBounds());
  await window.loadFile(join(root, 'overlay/out/renderer/index.html'));
  await window.webContents.executeJavaScript(`
    localStorage.setItem('overlay.avatarChoice', JSON.stringify('cat'));
    localStorage.setItem('overlay.skin', JSON.stringify('sticker'));
    localStorage.setItem('overlay.avatarFrame', JSON.stringify(${JSON.stringify(
      mode === 'danger' ? {x:1370,y:747,width:195,height:260} : {x:1680,y:747,width:195,height:260}
    )}));
    localStorage.setItem('overlay.webFrame', JSON.stringify({x:28,y:120,width:550,height:730}));
  `);
  await new Promise((done) => {
    window.webContents.once('did-finish-load', done);
    window.reload();
  });
  await waitFor(async () => {
    try { return await window.webContents.executeJavaScript("!!document.querySelector('.avatar-image')"); }
    catch { return false; }
  }, 'avatar renderer');
  await window.webContents.executeJavaScript(`
    document.body.style.backgroundImage = 'url(' + ${JSON.stringify(background)} + ')';
    document.body.style.backgroundSize = '1920px 1080px';
    document.body.style.backgroundRepeat = 'no-repeat';
  `);
  await waitFor(async () => (await health())?.connected, 'real overlay WebSocket');
  await delay(400);
  mkdirSync(output, { recursive: true });
  const scenes = mode === 'base' ? ['clean', 'debug'] : [mode];
  for (const scene of scenes) {
    if (scene === 'minecraft') {
      // Give the real wiki webview time to load before the short-lived reply subtitle.
      await fetch('http://127.0.0.1:8765/showcase/wiki', {method:'POST'});
      await delay(9000);
    }
    const reply = await fetch(`http://127.0.0.1:8765/showcase/${scene}`, {method: 'POST'});
    if (!reply.ok) throw new Error(await reply.text());
    await delay(1800);
    const image = await window.webContents.capturePage({x:0,y:0,width:1920,height:1080});
    const filename = join(output, scene === 'minecraft' ? 'minecraft-wiki.png' : `terraria-${scene}.png`);
    writeFileSync(filename, image.toPNG());
    console.log(`Saved ${filename} (${image.getSize().width} x ${image.getSize().height})`);
  }
  writeFileSync(join(output, `${mode}-showcase.txt`),
    'Manually scripted UI demonstration over a supplied gameplay screenshot.\n' +
    'Rendered by the real overlay using its WebSocket protocol. Boxes and dialogue are authored, not live model output.\n' +
    (mode === 'base' ? "World: Home Sweet Journey's Rest by TelBuilds.\n" +
    'https://www.curseforge.com/terraria/maps/home-sweet-journeys-rest\n' : '') +
    'HUD readings, attention, danger and voice-input text are manually supplied examples, not measurements.\n' +
    (mode === 'minecraft' ? 'Wiki: https://minecraft.wiki/w/Smite\n' : ''));
}

app.whenReady().then(run).catch((error) => {
  console.error(error);
  process.exitCode = 1;
}).finally(async () => {
  if (window && !window.isDestroyed()) window.destroy();
  if (server) {
    const exited = new Promise((done) => server.once('exit', done));
    server.kill();
    await exited;
  }
  app.quit();
});
