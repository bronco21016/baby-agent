"""Conversation log viewer — spins up a local HTTP server and opens the browser."""

from __future__ import annotations

import argparse
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .config import settings

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
  background: #fafafa; border: 1px solid #e5e5e5; border-radius: 8px;
  overflow: hidden; font-size: 12px;
}
summary {
  padding: 8px 12px; cursor: pointer; color: #6c7086; user-select: none;
  list-style: none; display: flex; align-items: center; gap: 6px;
}
summary::-webkit-details-marker { display: none; }
summary::before { content: "▶"; font-size: 9px; transition: transform 0.15s; }
details[open] summary::before { transform: rotate(90deg); }
.tool-call { padding: 10px 12px; border-top: 1px solid #e5e5e5; }
.tool-name { font-weight: 600; color: #1a1a1a; margin-bottom: 4px; font-family: monospace; }
.tool-label {
  font-size: 10px; color: #9ca3af; text-transform: uppercase;
  letter-spacing: .05em; margin: 8px 0 2px;
}
.tool-label:first-of-type { margin-top: 0; }
.tool-json {
  background: #f0f0f0; border-radius: 4px; padding: 6px 8px;
  font-family: monospace; font-size: 11px; white-space: pre-wrap;
  word-break: break-all; color: #374151; max-height: 200px; overflow-y: auto;
}
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
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function prettyJson(val) {
  if (typeof val === 'object' && val !== null) return JSON.stringify(val, null, 2);
  try { return JSON.stringify(JSON.parse(val), null, 2); } catch { return String(val); }
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
        <div class="tool-json">${esc(prettyJson(tc.input))}</div>
        <div class="tool-label">Result</div>
        <div class="tool-json">${esc(prettyJson(tc.result))}</div>
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

fetch('/data')
  .then(r => r.json())
  .then(data => {
    sessions = data;
    renderSidebar();
    if (sessions.length) selectSession(0);
  })
  .catch(() => {
    document.getElementById('chat').innerHTML =
      '<div id="empty">Failed to load data.</div>';
  });
</script>
</body>
</html>"""


def _load_sessions(path: Path) -> list[dict]:
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


class _Handler(BaseHTTPRequestHandler):
    log_path: Path  # set at class level before serving

    def do_GET(self) -> None:
        if self.path == "/":
            body = _HTML.encode()
            self._respond(200, "text/html; charset=utf-8", body)
        elif self.path == "/data":
            sessions = _load_sessions(self.log_path)
            body = json.dumps(sessions, default=str).encode()
            self._respond(200, "application/json", body)
        else:
            self.send_error(404)

    def _respond(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        pass  # silence per-request stdout noise


def run() -> None:
    parser = argparse.ArgumentParser(description="Browse baby-agent conversation logs.")
    parser.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    parser.add_argument(
        "--log",
        default=settings.conversation_log_path,
        help="Path to conversations.jsonl",
    )
    args = parser.parse_args()

    _Handler.log_path = Path(args.log)
    import socket
    local_ip = socket.gethostbyname(socket.gethostname())
    url = f"http://{local_ip}:{args.port}"
    print(f"Serving {args.log} → {url}  (Ctrl+C to stop)")
    server = HTTPServer(("0.0.0.0", args.port), _Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
