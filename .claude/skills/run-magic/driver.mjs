#!/usr/bin/env node
// CDP browser driver for the Magic LEA web app.
//
// No npm dependencies: uses Node 22's built-in global WebSocket + fetch to
// speak the Chrome DevTools Protocol directly. `chromium-cli`/Playwright are
// NOT installed in this environment, so this is the drive-the-browser harness.
//
// Subcommands (see SKILL.md for the canonical invocations):
//   shot   <url> <outfile>              navigate, settle, PNG screenshot
//   eval   <url> <jsExpr>               navigate, print JSON result of jsExpr
//   click  <url> <selector> <outfile>   navigate, click selector, screenshot
//   flow   <outfile>                    full scripted flow: start a human-vs-AI
//                                        game from the menu, screenshot the board
//
// Env:
//   APP_URL      base app url (default http://127.0.0.1:8010)
//   CHROME       path to chrome/edge exe (auto-detected on Windows if unset)
//   HEADED=1     launch a visible window instead of headless

import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const APP_URL = process.env.APP_URL || 'http://127.0.0.1:8010';
const PORT = 9222 + (process.pid % 1000);

function findChrome() {
  if (process.env.CHROME) return process.env.CHROME;
  const candidates = [
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  ];
  for (const c of candidates) {
    try { if (existsSync(c)) return c; } catch {}
  }
  return candidates[0];
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function launchChrome() {
  const userDir = mkdtempSync(join(tmpdir(), 'mtg-cdp-'));
  const headless = process.env.HEADED ? [] : ['--headless=new', '--disable-gpu'];
  const args = [
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${userDir}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--window-size=1400,900',
    ...headless,
    'about:blank',
  ];
  const proc = spawn(findChrome(), args, { stdio: 'ignore' });
  // Poll the version endpoint until the debug server answers.
  for (let i = 0; i < 100; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (r.ok) { await r.json(); return proc; }
    } catch {}
    await sleep(100);
  }
  throw new Error('Chrome devtools endpoint never came up');
}

// Minimal CDP client over a single page target.
class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); }
  static async attach() {
    // Find a page target (Chrome opens one for about:blank).
    let target;
    for (let i = 0; i < 50; i++) {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      target = list.find((t) => t.type === 'page');
      if (target) break;
      await sleep(100);
    }
    if (!target) throw new Error('no page target');
    const ws = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    const cdp = new CDP(ws);
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && cdp.pending.has(msg.id)) {
        const { res, rej } = cdp.pending.get(msg.id);
        cdp.pending.delete(msg.id);
        msg.error ? rej(new Error(JSON.stringify(msg.error))) : res(msg.result);
      }
    };
    return cdp;
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((res, rej) => this.pending.set(id, { res, rej }));
  }
  async navigate(url) {
    await this.send('Page.enable');
    await this.send('Runtime.enable');
    await this.send('Page.navigate', { url });
    // Wait for the app's JS to settle. The app boots its menu synchronously,
    // so a fixed settle plus a DOM-ready poll is reliable enough.
    await sleep(800);
    for (let i = 0; i < 30; i++) {
      const r = await this.eval('document.readyState');
      if (r === 'complete') break;
      await sleep(150);
    }
    await sleep(400);
  }
  async eval(expr) {
    const r = await this.send('Runtime.evaluate', {
      expression: `(()=>{ try { return JSON.stringify(${expr}); } catch(e){ return JSON.stringify({__err:String(e)}); } })()`,
      returnByValue: true, awaitPromise: true,
    });
    const v = r.result?.value;
    try { return JSON.parse(v); } catch { return v; }
  }
  async click(selector) {
    return this.eval(`(()=>{const el=document.querySelector(${JSON.stringify(selector)}); if(!el) return {clicked:false}; el.click(); return {clicked:true};})()`);
  }
  async shot(outfile) {
    const r = await this.send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(outfile, Buffer.from(r.data, 'base64'));
    return outfile;
  }
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const chrome = await launchChrome();
  let exitCode = 0;
  try {
    const cdp = await CDP.attach();
    if (cmd === 'shot') {
      const [url, out] = rest;
      await cdp.navigate(url || APP_URL);
      console.log('saved', await cdp.shot(out || 'shots/app.png'));
    } else if (cmd === 'eval') {
      const [url, expr] = rest;
      await cdp.navigate(url || APP_URL);
      console.log(JSON.stringify(await cdp.eval(expr), null, 2));
    } else if (cmd === 'click') {
      const [url, sel, out] = rest;
      await cdp.navigate(url || APP_URL);
      console.log('click', await cdp.click(sel));
      await sleep(600);
      console.log('saved', await cdp.shot(out || 'shots/click.png'));
    } else if (cmd === 'flow') {
      const [out] = rest;
      await cdp.navigate(APP_URL);
      console.log('home shown:', await cdp.eval('!!document.querySelector("#homeHostBtn")'));
      // Home -> Host Game page. Selectors are stable element ids from index.html.
      await cdp.click('#homeHostBtn');
      await sleep(500);
      // Mode select defaults to "human_vs_ai"; set it explicitly to be safe,
      // then click "Create Session" (#startBtn).
      console.log('host page:', await cdp.eval('!document.querySelector("#hostGamePage").classList.contains("hidden")'));
      await cdp.eval(`(()=>{const s=document.querySelector('#mode'); s.value='human_vs_ai'; s.dispatchEvent(new Event('change',{bubbles:true})); return s.value;})()`);
      await cdp.click('#startBtn');
      // Session creation hits the API and deals opening hands; give it time.
      await sleep(3500);
      const board = await cdp.eval('!document.querySelector("#boardPanel").classList.contains("hidden")');
      console.log('board visible:', board);
      // The battlefield is canvas-rendered (battlefield-canvas.js), so cards are
      // NOT DOM nodes. Prove the game is live via the prompt/turn text instead.
      console.log('prompt:', await cdp.eval('(document.querySelector("#promptTitle")||{}).textContent || null'));
      console.log('canvas:', await cdp.eval('!!document.querySelector("#battlefieldCanvasWrap canvas")'));
      console.log('saved', await cdp.shot(out || 'shots/flow.png'));
      if (!board) exitCode = 1;
    } else {
      console.error('usage: driver.mjs <shot|eval|click|flow> ...');
      exitCode = 2;
    }
  } catch (e) {
    console.error('ERROR', e.message);
    exitCode = 1;
  } finally {
    try { chrome.kill(); } catch {}
  }
  process.exit(exitCode);
}

main();
