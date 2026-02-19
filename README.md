# baby-agent

A voice-controlled baby tracking assistant for [Huckleberry](https://huckleberrycare.com/). Talk to it through Siri — it reads and writes your Huckleberry data using Claude AI.

```
Siri → iOS Shortcut → baby-agent server → Claude + Huckleberry → spoken reply
```

---

## Table of Contents

1. [Server Setup](#1-server-setup)
2. [Find Your Server's IP Address](#2-find-your-servers-ip-address)
3. [Create the iOS Shortcut](#3-create-the-ios-shortcut)
4. [Add the Shortcut to Siri](#4-add-the-shortcut-to-siri)
5. [Usage Examples](#5-usage-examples)
6. [Run the Server Automatically on Boot](#6-run-the-server-automatically-on-boot)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. Server Setup

**Requirements:** Python 3.11+, a machine on the same Wi-Fi network as your iPhone.

```bash
# Clone / enter the project directory
cd /home/admin/baby-agent

# Create a virtual environment and install
python -m venv .venv
.venv/bin/pip install --upgrade pip setuptools wheel
.venv/bin/pip install -e .

# Configure credentials
cp .env.example .env
nano .env          # fill in all values (see below)

# Start the server
.venv/bin/baby-agent
```

**.env values to fill in:**

| Key | Description |
|-----|-------------|
| `ANTHROPIC_API_KEY` | From [console.anthropic.com](https://console.anthropic.com) |
| `HUCKLEBERRY_EMAIL` | Your Huckleberry login email |
| `HUCKLEBERRY_PASSWORD` | Your Huckleberry password |
| `HUCKLEBERRY_TIMEZONE` | IANA timezone, e.g. `America/New_York` |

**Verify the server is running:**

```bash
curl http://localhost:8000/health
# Expected: {"status":"ok","huckleberry_authenticated":true,...}
```

---

## 2. Find Your Server's IP Address

The iOS Shortcut needs to reach the server over your local Wi-Fi network.

```bash
hostname -I | awk '{print $1}'
# Example output: 192.168.1.42
```

Write this down — you'll enter it into the shortcut in the next step.

> **Tip:** Assign your server a static IP in your router's DHCP settings so this address never changes.

---

## 3. Create the iOS Shortcut

Open the **Shortcuts** app on your iPhone. Tap **+** in the top-right corner to create a new shortcut.

Tap the title at the top and rename it to **"Baby Tracker"** (you'll say this name to Siri later).

Now add the following actions in order. To add each one, tap **+** (Add Action) and search for the action name shown in bold.

---

### Action 1 — Generate a session ID

This gives each conversation a unique ID so Claude remembers context across turns.

1. Search for **"Format Date"**
2. Set **Date** → tap the blue pill → select **"Current Date"**
3. Set **Format** → **Custom**
4. Set **Custom Format** → type: `yyyyMMddHHmmss`
5. Leave **Time Zone** as **Current**

> This produces a string like `20240315143022` — unique each time the shortcut runs.

6. Tap **Add to Shortcut**
7. Tap the result variable (it will say "Formatted Date") → tap **"Add Variable"** → name it **`session_id`**

---

### Action 2 — Start the conversation loop

1. Search for **"Repeat"**
2. Set the repeat count to **20** (this allows up to 20 back-and-forth turns)
3. Tap **Add to Shortcut** — you will now see a **Repeat / End Repeat** block. All remaining actions go *inside* this block.

---

### Action 3 — Get the user's voice input *(inside Repeat)*

1. Search for **"Ask for Input"**
2. Set **Input Type** → **Text**
3. Set **Prompt** → `What would you like to know?`
4. Tap **Add to Shortcut**
5. Tap the result → **"Add Variable"** → name it **`user_input`**

> When this runs via Siri, iOS will prompt you to speak. Your speech is transcribed to text automatically.

---

### Action 4 — Send the message to the server *(inside Repeat)*

1. Search for **"Get Contents of URL"**
2. Tap **Add to Shortcut**
3. Configure the action:

   **URL:**
   ```
   http://YOUR_SERVER_IP:8000/message
   ```
   Replace `YOUR_SERVER_IP` with the IP you found in Step 2 (e.g. `192.168.1.42`).

4. Tap **Show More**
5. Set **Method** → **POST**
6. Set **Request Body** → **JSON**
7. Tap **Add new field** → select **Text**:
   - **Key:** `session_id`
   - **Value:** tap the field → tap the variable icon (the box with a circle) → select **`session_id`**
8. Tap **Add new field** → select **Text**:
   - **Key:** `message`
   - **Value:** tap the field → tap the variable icon → select **`user_input`**
9. Leave Headers empty (Content-Type is set automatically for JSON body)

---

### Action 5 — Extract the reply *(inside Repeat)*

The server returns JSON like `{"session_id":"...","reply":"Sleep started.","turn_count":1,"conversation_done":true}`.

1. Search for **"Get Dictionary Value"**
2. Set **Get** → **Value**
3. Set **for Key** → type `reply`
4. Set **from** → tap the variable icon → select the result of **"Get Contents of URL"** (it may say "Contents of URL")
5. Tap **Add to Shortcut**

---

### Action 6 — Extract the done flag *(inside Repeat)*

1. Search for **"Get Dictionary Value"** again
2. Set **Get** → **Value**
3. Set **for Key** → type `conversation_done`
4. Set **from** → tap the variable icon → select **"Contents of URL"** (same response as above)
5. Tap **Add to Shortcut**

---

### Action 7 — Speak the reply *(inside Repeat)*

1. Search for **"Speak Text"**
2. Tap the text field → tap the variable icon → under **"Shortcut Input"** scroll to find the magic variable output of the **"Get Dictionary Value"** action from Action 5 (it will say "Dictionary Value") → select it
3. (Optional) Set **Wait Until Finished** → **On** so the next turn doesn't start while Claude is still talking
4. Tap **Add to Shortcut**

---

### Action 8 — Stop if the conversation is done *(inside Repeat, after Speak Text)*

The server sets `conversation_done` to `true` when it detects a natural end — the user said something like "thanks" or "that's all", or a one-shot action was completed with no follow-up expected.

1. Search for **"If"**
2. Tap the input field → tap the variable icon → select the magic variable output of the **"Get Dictionary Value"** action from Action 6 (it will say "Dictionary Value") → set **"is"** → type `1`

   > iOS Shortcuts represents a JSON boolean `true` as `1` in dictionary values.

3. Tap **Add to Shortcut** — you'll see **If / Otherwise / End If** blocks
4. Inside the **If** branch, search for **"Stop This Shortcut"** and add it there

---

### Finished shortcut — visual overview

```
[Shortcut: Baby Tracker]
│
├─ Format Date (Current Date, "yyyyMMddHHmmss")
│    └─ Set Variable: session_id
│
└─ Repeat 20 times
    ├─ Ask for Input (Text, "What would you like to know?")
    │    └─ Set Variable: user_input
    │
    ├─ Get Contents of URL
    │    URL: http://192.168.1.42:8000/message
    │    Method: POST
    │    Body (JSON):
    │      session_id → [session_id]
    │      message    → [user_input]
    │
    ├─ Get Dictionary Value "reply" from [Contents of URL]
    │
    ├─ Get Dictionary Value "conversation_done" from [Contents of URL]
    │
    ├─ Speak Text [Dictionary Value from Action 5]
    │
    ├─ If [Dictionary Value from Action 6 is 1]
    │    └─ Stop This Shortcut
    │  End If
   End Repeat
```

---

## 4. Add the Shortcut to Siri

1. Open the shortcut you just created
2. Tap the **⋯** (three dots) in the top-right corner → **Shortcut Details**
3. Tap **Add to Siri**
4. Record a phrase — say **"Track the baby"** or **"Baby tracker"**
5. Tap **Done**

Now you can start a conversation by saying:
> *"Hey Siri, track the baby"*

---

## 5. Usage Examples

Once the shortcut is running, just speak naturally. Examples:

| You say | Claude does |
|---------|-------------|
| "Is the baby sleeping?" | Checks live Huckleberry state and answers |
| "Start tracking sleep" | Calls `start_sleep`, confirms "Sleep started." |
| "She just woke up, end the sleep" | Calls `complete_sleep` |
| "Log a wet diaper" | Calls `log_diaper` with mode=wet |
| "She had 3 ounces of breast milk from a bottle" | Calls `log_bottle_feeding` |
| "Start a feeding on the left side" | Calls `start_feeding` with side=left |
| "Switch sides" | Calls `switch_feeding_side` |
| "Thanks, that's all" | Server detects the conversation is done and the shortcut stops |

Claude will ask a clarifying question if your request is ambiguous, then confirm every action taken.

---

## 6. Run the Server Automatically on Boot

So you don't have to manually start the server after a reboot, set it up as a systemd service.

**Create the service file:**

```bash
sudo nano /etc/systemd/system/baby-agent.service
```

**Paste this content** (adjust the paths if your username or project location differs):

```ini
[Unit]
Description=baby-agent Huckleberry voice assistant
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=admin
WorkingDirectory=/home/admin/baby-agent
EnvironmentFile=/home/admin/baby-agent/.env
ExecStart=/home/admin/baby-agent/.venv/bin/baby-agent
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Enable and start it:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable baby-agent
sudo systemctl start baby-agent

# Check it's running
sudo systemctl status baby-agent

# View live logs
sudo journalctl -u baby-agent -f
```

---

## 7. Troubleshooting

### Shortcut times out or shows an error

- Confirm the server is running: `curl http://YOUR_SERVER_IP:8000/health`
- Make sure your iPhone and the server are on the **same Wi-Fi network**
- The server URL in the shortcut must use `http://` not `https://`
- iOS may block non-HTTPS requests. If so, go to **Settings → Shortcuts → Allow Untrusted Shortcuts** (or add a local SSL certificate)

### "Get Contents of URL" returns nothing / empty

- In the shortcut, after "Get Contents of URL", add a **"Show Alert"** action temporarily and set its message to the URL result — this reveals raw errors from the server
- Check server logs: `sudo journalctl -u baby-agent -f`

### Siri doesn't hear me correctly / wrong words

- Speak clearly and at a normal pace
- If Siri mishears a key word (e.g. "sleep" → "slip"), Claude will usually infer the intent correctly from context
- You can also run the shortcut from the Shortcuts app and type instead of speaking

### Claude doesn't remember earlier turns

- Make sure your session_id variable is set **before** the Repeat loop and not regenerated inside it — only one Format Date action should exist, above the Repeat block
- Sessions expire after 30 minutes of inactivity (controlled by `SESSION_TTL_SECONDS` in `.env`)

### "Huckleberry not authenticated" (503 error)

- Check your `HUCKLEBERRY_EMAIL` and `HUCKLEBERRY_PASSWORD` in `.env`
- Restart the server after editing `.env`: `sudo systemctl restart baby-agent`

### Firebase state shows as "loading"

- The Huckleberry realtime listeners take a few seconds to receive their first snapshot after startup
- Wait 5–10 seconds after starting the server before the first query
- State will update in real time after that initial load

### Server responds but Siri doesn't speak the reply

- Confirm the "Speak Text" action has the `reply` variable selected, not literal text
- Make sure "Wait Until Finished" is **On** on the Speak Text action
- Try running the shortcut manually (tap it in the Shortcuts app) to isolate Siri-specific issues
