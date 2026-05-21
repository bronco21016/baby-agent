"""Conversation log viewer mounted at /conversations on the main FastAPI app."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from .config import settings

router = APIRouter(prefix="/conversations", tags=["viewer"])

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>baby-agent logs</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, sans-serif; display: flex; height: 100vh; background: #f5f5f5; color: #1a1a1a; }

#sidebar {
  width: 280px; min-width: 200px; background: #1e1e2e; color: #cdd6f4;
  overflow-y: auto; flex-shrink: 0; border-right: 1px solid #313244;
  display: flex; flex-direction: column;
}
#sidebar h1 {
  font-size: 12px; font-weight: 600; color: #89b4fa; padding: 14px 16px;
  letter-spacing: .06em; text-transform: uppercase; border-bottom: 1px solid #313244;
  flex-shrink: 0;
}
#session-list { overflow-y: auto; flex: 1; }
.session-item {
  padding: 12px 16px; cursor: pointer; border-bottom: 1px solid #313244;
  transition: background 0.1s;
}
.session-item:hover { background: #313244; }
.session-item.active { background: #45475a; }
.session-date { font-size: 11px; color: #6c7086; margin-bottom: 4px; }
.session-preview { font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.session-meta { font-size: 11px; color: #6c7086; margin-top: 4px; display: flex; align-items: center; gap: 4px; }
.dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; }
.dot-done { background: #a6e3a1; }
.dot-open { background: #f9e2af; }

#main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
#main-header {
  padding: 12px 20px; background: white; border-bottom: 1px solid #e5e5e5;
  font-size: 12px; color: #6c7086; flex-shrink: 0;
}
#chat { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 20px; }
#empty { flex: 1; display: flex; align-items: center; justify-content: center; color: #9ca3af; font-size: 14px; }

.turn { display: flex; flex-direction: column; gap: 8px; }
.turn-ts { font-size: 11px; color: #9ca3af; text-align: center; padding: 4px 0; }

.bubble-user {
  align-self: flex-end; background: #4f46e5; color: white;
  padding: 10px 14px; border-radius: 16px 16px 4px 16px;
  max-width: 68%; font-size: 14px; line-height: 1.5;
}
.bubble-reply {
  align-self: flex-start; background: white; border: 1px solid #e5e5e5;
  padding: 10px 14px; border-radius: 16px 16px 16px 4px;
  max-width: 68%; font-size: 14px; line-height: 1.5;
}

.tool-block { align-self: stretch; }
details {
  background: #1e1e2e; border: 1px solid #313244; border-radius: 8px;
  overflow: hidden; font-size: 12px;
}
summary {
  padding: 8px 12px; cursor: pointer; color: #89b4fa; user-select: none;
  list-style: none; display: flex; align-items: center; gap: 6px;
  font-size: 11px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
}
summary::-webkit-details-marker { display: none; }
summary::before { content: "▶"; font-size: 9px; transition: transform 0.15s; }
details[open] summary::before { transform: rotate(90deg); }
.tool-call { padding: 12px; border-top: 1px solid #313244; }
.tool-call + .tool-call { border-top: 1px solid #313244; }
.tool-name { font-weight: 700; color: #cba6f7; margin-bottom: 8px; font-family: monospace; font-size: 13px; }
.tool-label {
  font-size: 10px; color: #6c7086; text-transform: uppercase;
  letter-spacing: .06em; margin: 10px 0 4px;
}
.tool-label:first-of-type { margin-top: 0; }
.tool-json {
  background: #181825; border-radius: 6px; padding: 8px 10px;
  font-family: 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
  font-size: 11.5px; line-height: 1.6; white-space: pre-wrap;
  word-break: break-all; max-height: 240px; overflow-y: auto;
  border: 1px solid #313244;
}

/* JSON syntax colours (Catppuccin-ish) */
.j-key   { color: #89b4fa; }   /* blue  — keys */
.j-str   { color: #a6e3a1; }   /* green — string values */
.j-num   { color: #fab387; }   /* peach — numbers */
.j-bool  { color: #f38ba8; }   /* red   — true/false */
.j-null  { color: #6c7086; }   /* grey  — null */
.j-punc  { color: #9399b2; }   /* overlay — brackets/braces/commas */
</style>
</head>
<body>
<div id="sidebar">
  <h1>baby-agent logs</h1>
  <div id="session-list"></div>
</div>
<div id="main">
  <div id="main-header">Select a conversation</div>
  <div id="chat"><div id="empty">← pick a session</div></div>
</div>
<script>
let sessions = [];

function fmtDateTime(ts) {
  return new Date(ts).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
  });
}
function fmtDateOnly(ts) {
  return new Date(ts).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric'
  });
}
function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function highlight(val) {
  let str;
  if (typeof val === 'object' && val !== null) {
    str = JSON.stringify(val, null, 2);
  } else {
    try { str = JSON.stringify(JSON.parse(String(val)), null, 2); }
    catch { str = String(val); }
  }
  // Tokenise and wrap in spans; process char-by-char via regex
  return str.replace(
    /("(?:\\.|[^"\\])*")\s*:|("(?:\\.|[^"\\])*")|(true|false)|(null)|(-?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?)|([{}\[\],:])/g,
    (_, key, strVal, bool, nil, num, punc) => {
      if (key)    return `<span class="j-key">${esc(key)}</span>:`;
      if (strVal) return `<span class="j-str">${esc(strVal)}</span>`;
      if (bool)   return `<span class="j-bool">${bool}</span>`;
      if (nil)    return `<span class="j-null">null</span>`;
      if (num)    return `<span class="j-num">${num}</span>`;
      if (punc)   return `<span class="j-punc">${esc(punc)}</span>`;
      return _;
    }
  );
}

function renderSidebar() {
  document.getElementById('session-list').innerHTML = sessions.map((s, i) => {
    const done = s.turns.at(-1)?.conversation_done;
    const dotClass = done ? 'dot-done' : 'dot-open';
    const label = done ? 'done' : 'open';
    const n = s.turns.length;
    return `<div class="session-item" data-i="${i}" onclick="selectSession(${i})">
      <div class="session-date">${fmtDateOnly(s.start_ts)}</div>
      <div class="session-preview">${esc(s.turns[0]?.user ?? '')}</div>
      <div class="session-meta">
        <span class="dot ${dotClass}"></span>${label} &middot; ${n} turn${n !== 1 ? 's' : ''}
      </div>
    </div>`;
  }).join('');
}

function selectSession(i) {
  document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));
  document.querySelector(`.session-item[data-i="${i}"]`)?.classList.add('active');
  const s = sessions[i];
  document.getElementById('main-header').textContent =
    `${fmtDateTime(s.start_ts)}  ·  session ${s.session_id}`;
  document.getElementById('chat').innerHTML = s.turns.map(renderTurn).join('');
}

function renderTurn(t) {
  let toolHtml = '';
  if (t.tool_calls && t.tool_calls.length) {
    const n = t.tool_calls.length;
    const callsHtml = t.tool_calls.map(tc => `
      <div class="tool-call">
        <div class="tool-name">${esc(tc.name)}</div>
        <div class="tool-label">Input</div>
        <div class="tool-json">${highlight(tc.input)}</div>
        <div class="tool-label">Result</div>
        <div class="tool-json">${highlight(tc.result)}</div>
      </div>`).join('');
    toolHtml = `<div class="tool-block">
      <details>
        <summary>${n} tool call${n !== 1 ? 's' : ''}</summary>
        ${callsHtml}
      </details>
    </div>`;
  }
  return `<div class="turn">
    <div class="turn-ts">${fmtDateTime(t.ts)} &middot; turn ${t.turn}</div>
    <div class="bubble-user">${esc(t.user)}</div>
    ${toolHtml}
    <div class="bubble-reply">${esc(t.reply)}</div>
  </div>`;
}

fetch('/conversations/data')
  .then(r => r.json())
  .then(data => {
    sessions = data;
    renderSidebar();
    if (sessions.length) selectSession(0);
  })
  .catch(() => {
    document.getElementById('chat').innerHTML = '<div id="empty">Failed to load data.</div>';
  });
</script>
</body>
</html>"""


def _load_sessions() -> list[dict]:
    path = Path(settings.conversation_log_path)
    if not path.exists():
        return []

    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    by_session: dict[str, list[dict]] = {}
    for row in rows:
        sid = row.get("session_id", "unknown")
        by_session.setdefault(sid, []).append(row)

    sessions = [
        {
            "session_id": sid,
            "start_ts": turns[0]["ts"],
            "turns": sorted(turns, key=lambda t: t.get("turn", 0)),
        }
        for sid, turns in by_session.items()
    ]
    sessions.sort(key=lambda s: s["start_ts"], reverse=True)
    return sessions


@router.get("", response_class=HTMLResponse)
async def viewer_page() -> str:
    return _HTML


@router.get("/data")
async def viewer_data() -> JSONResponse:
    return JSONResponse(_load_sessions())
