# BanterBox Implementation Prompt (Coding Model)

You are implementing **BanterBox** from a greenfield empty git repo. No existing application code. Build the full MVP in one pass: working duplex voice, deterministic tools that mutate UI, commentary SFX, barge-in, latency HUD.

Do not ask clarifying questions. Follow this spec exactly. Do not add extra features, auth, Docker, or a real sports API.

---

## 0. Locked stack

- **Monorepo:** `backend/` (Python 3.12, FastAPI, uvicorn, websockets) + `frontend/` (Vite, React 18, TypeScript, Tailwind, Zustand, Lucide).
- **STT:** Deepgram Nova-2 streaming WS (`linear16`, `16000`, `channels=1`, `vad_events=true`, `interim_results=true`, `endpointing=300`).
- **LLM:** OpenAI `gpt-4o-mini` streaming chat completions + tool calls (`stream=True`, `tool_choice=auto`, `temperature=0.7`, `max_tokens=120`).
- **TTS:** Cartesia Sonic WebSocket, PCM `s16le` @ 24000 Hz, one voice ID per mode. Sentence-flush: start TTS as soon as the first clause (`.!?`) or 12 tokens arrive; do not wait for the full LLM turn.
- **Data:** in-memory JSON rivalries; unknown pairs return a mock payload (never block on network).
- **Transport:** single WS `GET /ws/voice`. JSON text frames only (audio is base64 inside JSON).

**Env vars** (`.env` gitignored; `.env.example` committed):

```
DEEPGRAM_API_KEY=
OPENAI_API_KEY=
CARTESIA_API_KEY=
CARTESIA_VOICE_DRAMATIC=     # fallback: any Sonic English voice
CARTESIA_VOICE_SPARRING=
CARTESIA_VOICE_ANALYST=
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
CORS_ORIGINS=http://localhost:5173
```

If a vendor key is missing, the server must still boot and emit `error` frames with `recoverable=false` on first use of that vendor.

---

## 1. File tree (create every file)

```
.gitignore
.env.example
README.md
backend/requirements.txt
backend/app/__init__.py
backend/app/main.py
backend/app/config.py
backend/app/protocol.py
backend/app/session.py
backend/app/pipeline.py
backend/app/audio_util.py
backend/app/metrics.py
backend/app/stt/__init__.py
backend/app/stt/deepgram.py
backend/app/llm/__init__.py
backend/app/llm/prompts.py
backend/app/llm/engine.py
backend/app/llm/tools.py
backend/app/tts/__init__.py
backend/app/tts/cartesia.py
backend/app/tools/__init__.py
backend/app/tools/registry.py
backend/app/tools/lookup_h2h.py
backend/app/data/rivalries.json
frontend/package.json
frontend/tsconfig.json
frontend/tsconfig.app.json
frontend/vite.config.ts
frontend/tailwind.config.js
frontend/postcss.config.js
frontend/index.html
frontend/src/main.tsx
frontend/src/App.tsx
frontend/src/index.css
frontend/src/vite-env.d.ts
frontend/src/lib/protocol.ts
frontend/src/lib/wsClient.ts
frontend/src/lib/pcm.ts
frontend/src/lib/audioCapture.ts
frontend/src/lib/audioPlayback.ts
frontend/src/lib/sfx.ts
frontend/src/worklets/pcm-processor.js
frontend/src/store/sessionStore.ts
frontend/src/components/MicGate.tsx
frontend/src/components/LatencyHUD.tsx
frontend/src/components/TranscriptFeed.tsx
frontend/src/components/ComparisonCard.tsx
frontend/src/components/AgentStateBadge.tsx
frontend/src/assets/sfx/stadium_roar.wav
frontend/src/assets/sfx/referee_whistle.wav
frontend/src/assets/sfx/boo_crowd.wav
frontend/src/assets/sfx/siuuu_chant.wav
```

SFX: generate short royalty-free-style WAVs with a tiny Python/sox snippet **or** use Web Audio oscillators in `sfx.ts` as a fallback if binary assets are awkward. Prefer real short WAV clips (~1–2s). Do not block the app if a file is missing — synthesize a beep/noise burst instead.

---

## 2. WebSocket protocol (canonical)

All messages are JSON objects with required `event: string`. Unknown events are ignored (log + continue). Validate with Pydantic on the server and a TS discriminated union on the client.

### 2.1 Client → Server

**`audio_data`**

```json
{"event":"audio_data","payload":"<base64>","seq":0}
```

- `payload`: raw **s16le mono 16 kHz** PCM, typically 20 ms = 640 bytes → 856-char base64.
- `seq`: uint, monotonic per session, for drop detection.

**`user_interrupted`**

```json
{"event":"user_interrupted","reason":"vad"|"manual","client_timestamp":1728250000000}
```

**`ping`**

```json
{"event":"ping","client_timestamp":1728250000000}
```

**`client_ready`** (send once after mic + AudioContext granted)

```json
{"event":"client_ready","sample_rate_in":16000,"sample_rate_out_preferred":24000}
```

### 2.2 Server → Client

**`session_ready`**

```json
{"event":"session_ready","session_id":"uuid","mode":"pub_sparring_partner"}
```

**`pong`**

```json
{"event":"pong","client_timestamp":1728250000000,"server_timestamp":1728250000120}
```

**`agent_state`**

```json
{"event":"agent_state","state":"listening"|"thinking"|"speaking"|"interrupted"}
```

States: `listening` (idle + capturing), `thinking` (LLM started, no audio yet), `speaking` (TTS chunks flowing), `interrupted` (barge-in; then immediately back to `listening`).

**`transcript_stream`**

```json
{"event":"transcript_stream","role":"user"|"agent","delta":"string","is_final":false,"turn_id":"uuid"}
```

- User: Deepgram interim (`is_final=false`) then final (`is_final=true`). Replace the open user bubble on interim; freeze on final.
- Agent: LLM token deltas; `is_final=true` once on finish.

**`tool_executed`**

```json
{
  "event":"tool_executed",
  "tool_name":"lookup_head_to_head"|"trigger_stadium_audio"|"switch_commentary_mode",
  "turn_id":"uuid",
  "data":{}
}
```

Broadcast **before** TTS of the spoken sentence that references the tool. UI must render immediately.

**`audio_output`**

```json
{"event":"audio_output","payload":"<base64 s16le>","sample_rate":24000,"turn_id":"uuid","seq":0}
```

**`audio_output_end`**

```json
{"event":"audio_output_end","turn_id":"uuid"}
```

**`metrics`**

```json
{"event":"metrics","turn_id":"uuid","stt_final_ms":90,"llm_ttft_ms":140,"tts_ttfa_ms":210,"total_turnaround_ms":480}
```

- `stt_final_ms`: user speech-end → Deepgram `is_final`.
- `llm_ttft_ms`: STT final → first LLM token.
- `tts_ttfa_ms`: first LLM token → first `audio_output` sent.
- `total_turnaround_ms`: user speech-end → first `audio_output` (this is TTFA; target **< 600**).

**`error`**

```json
{"event":"error","code":"STT_DISCONNECT"|"LLM_ERROR"|"TTS_ERROR"|"BAD_FRAME"|"TOOL_ERROR"|"SESSION_FATAL","message":"human string","recoverable":true,"turn_id":null}
```

**`mode_changed`**

```json
{"event":"mode_changed","mode":"dramatic_commentator"|"pub_sparring_partner"|"data_analyst"}
```

### 2.3 Pydantic models (`backend/app/protocol.py`)

Use a tagged union. Reject extra-large `audio_data` (`payload` decoded > 64 KiB). On `ValidationError` send `BAD_FRAME` and continue the session.

Mirror 1:1 in `frontend/src/lib/protocol.ts`.

---

## 3. Session orchestrator (`session.py` + `pipeline.py`)

One `VoiceSession` per WS connection.

```
mic PCM ──► Deepgram ──► on utterance end ──► OpenAI stream
                                              ├─ tool_calls ──► execute ──► tool_executed WS + tool result back to LLM
                                              └─ text deltas ──► sentence buffer ──► Cartesia ──► audio_output WS
user_interrupted ──► cancel LLM Task, abort TTS WS, increment turn_epoch (client drops stale seq/turn_id)
```

### 3.1 Turn state machine

```
IDLE ──(Deepgram speech_started)──► USER_SPEAKING
USER_SPEAKING ──(UtteranceEnd / is_final)──► THINKING  (create turn_id, cancel any prior agent turn)
THINKING ──(first TTS byte)──► SPEAKING
SPEAKING ──(audio_output_end)──► IDLE
ANY ──(user_interrupted OR Deepgram barge-in while SPEAKING)──► INTERRUPTED ──► IDLE
```

Rules:

- Only **final** user transcripts start an LLM turn. Interims update UI only.
- Ignore finals with empty/whitespace or `< 2` chars.
- `turn_epoch: int` increments on interrupt and on new user final. Pipeline tasks capture epoch at start; if epoch changed, drop all remaining emits.
- Never overlap two SPEAKING turns. New user final while SPEAKING is treated as barge-in then new turn.

### 3.2 Barge-in routine (exact)

On `user_interrupted` **or** Deepgram `speech_started` while `state in {THINKING, SPEAKING}`:

1. `session.turn_epoch += 1`
2. Cancel `asyncio.Task` for LLM (`task.cancel()`; swallow `CancelledError`).
3. Call `tts.abort()` which closes the Cartesia WS and clears the server send queue.
4. Send `agent_state=interrupted`, then `agent_state=listening`.
5. Do **not** send `audio_output_end` for the killed turn (client already flushed).
6. Resume forwarding mic PCM to Deepgram (never pause STT).

Client barge-in (must happen **before** waiting for server):

1. RMS/VAD in the worklet: if playback active and frame RMS > threshold for 3 consecutive 20 ms frames (~80–100 ms of speech), fire interrupt.
2. Immediately `playback.flush()` (stop all `AudioBufferSourceNode`, reset scheduler clock).
3. Send `user_interrupted`.
4. Keep capturing; do not mute the mic.

### 3.3 Error handling matrix

| Failure | Action |
|---|---|
| Deepgram WS drop | reconnect with backoff 200ms, 500ms, 1s, 2s (max 5); send `STT_DISCONNECT recoverable=true`; if all fail, `SESSION_FATAL` and close 1011 |
| OpenAI stream error / timeout 8s | `LLM_ERROR`; speak nothing; `agent_state=listening`; log traceback |
| Cartesia drop mid-utterance | `TTS_ERROR recoverable=true`; stop that turn; keep session |
| Tool exception | `TOOL_ERROR`; feed LLM a tool result `{"error":"..."}` so it can still talk; UI gets no card |
| Client JSON parse | `BAD_FRAME`; continue |
| WS idle 45s without ping | server sends ping-offered `agent_state` keep-alive; close 1001 after 90s no frames |

Wrap every vendor call in `try/except`. Never crash the WS handler.

### 3.4 Latency strategy (hit 600 ms TTFA)

- Capture frames **20 ms**, not 250 ms.
- Deepgram `endpointing=300` (ms of silence).
- LLM `max_tokens=120`. Tools are local dict lookups (< 1 ms).
- **Sentence flush:** TTS on first of: (a) `.!?` in accumulated text, (b) 12 tokens, (c) tool-call round completed and first tokens after it. Strip incomplete words before flush.
- Cartesia: start WS **at session start** and keep it warm (or reconnect in <50 ms); do not open a new WS per sentence if the SDK allows a persistent socket. If not, open on THINKING entry.
- Do not wait for `audio_output_end` of previous sentence before starting the next sentence’s TTS within the same turn.
- Metrics timestamps: `perf_counter()` on server; include `total_turnaround_ms` on first `audio_output`.

---

## 4. Audio buffer management

### 4.1 Client capture (`pcm-processor.js` + `audioCapture.ts`)

- `getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } })`
- `AudioContext` (device rate, usually 48 kHz) → `AudioWorkletNode` (`pcm-processor`).
- Worklet: ring buffer, downsample to 16 kHz with simple average decimation (or linear interpolation), emit `Int16Array` frames of **320 samples (20 ms)**.
- Main thread: base64-encode, `{event:audio_data, payload, seq++}`.
- Do not use `MediaRecorder`. Do not send 48 kHz. Do not send float32.

Worklet RMS (for barge-in): post `{type:"rms", value}` each frame. Threshold default `0.02` (tunable const `BARGE_IN_RMS = 0.025`). Require 3 hot frames while `isPlaying`.

### 4.2 Client playback (`audioPlayback.ts`) — clickless queue

Incoming 24 kHz s16le chunks:

1. Decode to `Float32Array` in [-1, 1].
2. Create `AudioBuffer` (1 channel, 24000).
3. **Jitter buffer:** hold until `queuedMs >= 60` **or** 3 chunks, then start.
4. Schedule `AudioBufferSourceNode` at `nextStartTime = max(ctx.currentTime + 0.02, nextStartTime)`; after each node, `nextStartTime += buffer.duration`.
5. Apply 5 ms linear fade-in on the first buffer of a turn and 5 ms fade-out on `flush()`.
6. **Gap fill:** if `nextStartTime - ctx.currentTime < 0.01` and queue empty, insert 20 ms of silence rather than letting the clock fall behind (prevents pile-up after underrun).
7. `flush()`: `sources.forEach(s => { try { s.stop(0) } catch {} })`; `sources.clear()`; `nextStartTime = 0`; `queuedMs = 0`.
8. Drop any `audio_output` whose `turn_id` ≠ current `agentTurnId` (set on first audio of a turn; cleared on interrupt).

Playback `AudioContext` sampleRate: use a dedicated context; if the context is not 24000, resample with linear interpolation in `pcm.ts` (`resampleLinear(input, 24000, ctx.sampleRate)`).

### 4.3 Server PCM (`audio_util.py`)

Helpers: `b64_to_pcm16`, `pcm16_to_b64`, size checks, optional RMS. No resampling on the server (Deepgram wants 16 kHz in; Cartesia gives 24 kHz out).

---

## 5. Tools — OpenAI schemas + execution

Define in `backend/app/llm/tools.py` as OpenAI tool dicts. Execute in `backend/app/tools/registry.py`. After each successful execution, **immediately** `ws.send(tool_executed)` then return JSON string to the LLM as `role=tool`.

### 5.1 `lookup_head_to_head`

```json
{
  "type":"function",
  "function":{
    "name":"lookup_head_to_head",
    "description":"Fetch head-to-head records, trophies, and banter hooks for two players or clubs. Call whenever the user compares two entities, names a rivalry, or makes a biased claim that needs facts.",
    "parameters":{
      "type":"object",
      "additionalProperties":false,
      "properties":{
        "entity_a":{"type":"string"},
        "entity_b":{"type":"string"},
        "sport":{"type":"string","enum":["football","cricket","auto"]}
      },
      "required":["entity_a","entity_b","sport"]
    }
  }
}
```

**Resolution:** lowercase, strip "fc"/"the", alias match against `rivalries.json`. If `sport=auto`, try football then cricket.

**Success `data` payload** (this is what the frontend card renders):

```json
{
  "sport":"football",
  "entity_a":{
    "name":"Lionel Messi",
    "short":"Messi",
    "accent":"#78B6FF",
    "stats":{"Ballon d'Or":8,"UCL":4,"World Cups":1,"Club goals":850}
  },
  "entity_b":{
    "name":"Cristiano Ronaldo",
    "short":"Ronaldo",
    "accent":"#E8B923",
    "stats":{"Ballon d'Or":5,"UCL":5,"World Cups":0,"Club goals":890}
  },
  "h2h":{"meetings":36,"a_wins":16,"b_wins":10,"draws":10,"label":"Meetings as opponents"},
  "banter_hook":"Messi leads the Ballon d'Or tally; Ronaldo owns the UCL edge.",
  "matched":true
}
```

**Miss payload** (`matched:false`) still returns a card so the demo never looks empty:

```json
{
  "sport":"football",
  "entity_a":{"name":"<A>","short":"<A>","accent":"#78B6FF","stats":{"Titles":"—","Win rate":"—"}},
  "entity_b":{"name":"<B>","short":"<B>","accent":"#E8B923","stats":{"Titles":"—","Win rate":"—"}},
  "h2h":{"meetings":0,"a_wins":0,"b_wins":0,"draws":0,"label":"No archive row — mock split"},
  "banter_hook":"Archive's cold on this one, so treat these numbers as pub-math, not gospel.",
  "matched":false
}
```

### 5.2 `trigger_stadium_audio`

```json
{
  "type":"function",
  "function":{
    "name":"trigger_stadium_audio",
    "description":"Play a client-side stadium stinger. Call for dramatic goals, controversial calls, cocky punchlines, or Ronaldo-style moments.",
    "parameters":{
      "type":"object",
      "additionalProperties":false,
      "properties":{
        "effect":{"type":"string","enum":["stadium_roar","referee_whistle","boo_crowd","siuuu_chant"]}
      },
      "required":["effect"]
    }
  }
}
```

`tool_executed.data` = `{"effect":"stadium_roar"}`. Frontend `sfx.ts` plays it on a **separate** gain node (does not go through the TTS scheduler; do not flush TTS). Default gain 0.45.

Heuristic (also in the system prompt): 90th-minute winners, bicycle kicks, last-ball sixes → `stadium_roar`. Dives / robberies → `boo_crowd`. Ronaldo mentions in celebration context → `siuuu_chant`. Foul / VAR / offside drama → `referee_whistle`.

### 5.3 `switch_commentary_mode`

```json
{
  "type":"function",
  "function":{
    "name":"switch_commentary_mode",
    "description":"Change persona and voice. Call when the user asks to commentate, debate, or wants dry stats.",
    "parameters":{
      "type":"object",
      "additionalProperties":false,
      "properties":{
        "mode":{"type":"string","enum":["dramatic_commentator","pub_sparring_partner","data_analyst"]}
      },
      "required":["mode"]
    }
  }
}
```

Effects: update `session.mode`, swap Cartesia `voice_id`, swap system prompt for **subsequent** generation in this same turn if tools ran first (include the new prompt in the follow-up completion). Send both `tool_executed` and `mode_changed`.

Auto-switch without being asked:

- User says "commentate / call this / 90th minute / bicycle kick" → `dramatic_commentator`
- User wants a debate / "you're wrong" / "Arsenal never bottled" → stay or switch to `pub_sparring_partner`
- User asks for numbers only → `data_analyst`

---

## 6. `rivalries.json` (seed at least these 12)

Each row: `id`, `sport`, `aliases[]`, `entity_a`, `entity_b`, `h2h`, `banter_hook`.

Must include:

1. Messi vs Ronaldo (football)
2. Real Madrid vs Barcelona
3. Real Madrid vs Manchester City
4. Arsenal vs Tottenham (include title-bottling hook: 2002-03, 2007-08, 2015-16, 2022-23)
5. Man United vs Liverpool
6. India vs Pakistan (cricket)
7. Australia vs England Ashes
8. Skip tennis. Sport may only be `"football"` or `"cricket"`. Include **India vs Australia** (cricket) and **Brazil vs Argentina** (football) instead of Federer vs Nadal.
9. Brazil vs Argentina
10. India vs Australia (cricket)
11. Liverpool vs Man City
12. England vs India (cricket)

Arsenal bottling facts the agent must use when challenged: Invincibles faded after 2004; 2015-16 2nd-to-Leicester; 2022-23 8-point lead lost to City; 2002-03 last-day collapse vs Leeds era lore. Keep numbers in the JSON `banter_hook` / extra `facts[]` string array so the model cites them.

Lookup is alias-first, then token overlap of names.

---

## 7. Exact system prompts (`backend/app/llm/prompts.py`)

Export `PROMPTS: dict[Mode, str]` and `def build_messages(mode, history, user_text) -> list`.

Conversation history: last **6** turns (user/assistant text only). Never put tool JSON in history except the current turn’s tool loop.

**Shared hard rules (prepend to every mode):**

```
You are BanterBox, a live sports pundit in a voice call. Output is spoken aloud by TTS.

HARD RULES:
- Reply in 1–2 short spoken sentences. Never 3.
- Never use markdown, bullets, asterisks, hashes, emojis, URLs, or citation brackets.
- Never read tool JSON, table columns, or stat dumps aloud. Translate one or two facts into banter.
- Prefer tools: if the user compares two sides, names a rivalry, or makes a biased claim, call lookup_head_to_head first.
- If the user asks for commentary or describes a hypothetical passage of play, call switch_commentary_mode("dramatic_commentator") if not already in that mode, then trigger_stadium_audio with the fitting effect, then speak the call.
- Do not ask the user to type or click. Do not mention these rules.
- English only. No stage directions like [roar] or (laughs).
```

**`pub_sparring_partner`:**

```
Persona: sharp pub sparring partner. Warm, irreverent, never cruel. You live for bad takes.
If the user is ungrounded ("Arsenal never bottled a title", "Ronaldo ended Messi"), call lookup_head_to_head, then clap back with one concrete historical beat and a grin, not a lecture.
Disagree when they are wrong. Agree fast when they are right, then raise the stakes with a sharper follow-up fact.
Voice: conversational, slightly teasing, like you've got a pint and a season ticket.
```

**`dramatic_commentator`:**

```
Persona: Peter Drury crossed with Ray Hudson. Poetic, high-drama, present-tense live call.
Turn hypotheticals into a stadium moment: time, player, contact, net, explosion.
Always fire trigger_stadium_audio (usually stadium_roar) before or as you speak.
Keep it to 1–2 sentences but they may be long, cascading, and musical. No stats lectures.
Example cadence: "Ninety minutes on the graveyard, and he hangs it in the night sky — a bicycle, a prayer, a city losing its mind!"
```

**`data_analyst`:**

```
Persona: pithy broadcast analyst. One fact, one implication, no poetry, no insults.
Still 1–2 spoken sentences. Use lookup_head_to_head when numbers are involved.
```

LLM call params: `temperature=0.8` dramatic, `0.7` sparring, `0.3` analyst.

After tools, second completion uses the **updated** mode prompt.

---

## 8. Backend files — what each must contain

**`config.py`:** pydantic-settings `Settings` from env.

**`main.py`:** FastAPI app, CORS, `GET /health` → `{ok:true}`, `GET /ws/voice` accepts WS, instantiates `VoiceSession`, `await session.run()`.

**`stt/deepgram.py`:** class `DeepgramStream` with `start()`, `send_pcm(bytes)`, `close()`. Callbacks: `on_interim(text)`, `on_final(text)`, `on_speech_started()`, `on_utterance_end()`, `on_error()`. Use `wss://api.deepgram.com/v1/listen?model=nova-2&encoding=linear16&sample_rate=16000&channels=1&interim_results=true&vad_events=true&utterance_end_ms=1000&endpointing=300`. Keep-alive text `{"type":"KeepAlive"}` every 8s.

**`llm/engine.py`:** `stream_turn(messages, tools, on_delta, on_tool_calls, epoch_check)`. Parse SSE tool-call fragments; assemble `tool_calls` then yield control to registry; then continue. Abort if `epoch_check()` fails.

**`tts/cartesia.py`:** `CartesiaTTS` with `synthesize(text, voice_id, on_chunk, epoch_check)` and `abort()`. Request PCM 24 kHz. Stream chunks out as soon as bytes arrive.

**`metrics.py`:** `TurnClock` with marks `user_end`, `stt_final`, `llm_first`, `tts_first`; `emit()` dict.

**`pipeline.py`:** glue: on_final → clock.start → agent_state thinking → OpenAI (loop tools) → sentence-flush TTS → metrics on first audio.

Do not block the event loop with sync HTTP. Use `httpx`/`websockets`/`openai.AsyncOpenAI`.

---

## 9. Frontend UX (single page, dark stadium HUD)

Layout (`App.tsx`), 1280-wide max, dark (`#07090d` bg, pitch-green `#0a7a3e` accents):

- **Top bar:** wordmark `BANTERBOX`, `AgentStateBadge`, `LatencyHUD` (STT / TTFT / TTFA / RTT from ping).
- **Left column:** `TranscriptFeed` dual bubbles (user slate, agent gold). Show interim user text in italic opacity-70.
- **Right column:** `ComparisonCard` empty state “Waiting for a rivalry…”; when `lookup_head_to_head` fires, ESPN-style two-column card (names, 2x2 stats, H2H bar, banter hook). Persist last card.
- **Bottom:** `MicGate` — first click is **the only button**: “Tap to enter the box” requests mic + starts WS + capture. After that, fully hands-free. Show a pulsing ring while `listening`, bars while `speaking`.
- Connection pill: `live` / `reconnecting` / `down`. Auto-reconnect WS with backoff.

`ComparisonCard` must appear **as soon as** `tool_executed` arrives, even if the agent has not spoken yet.

Visual language: broadcast lower-third, not chatbot chrome. Tailwind only. Lucide icons: `Mic`, `Radio`, `Swords`, `Gauge`.

Hands-free after gate: no push-to-talk.

---

## 10. README (required in the app repo)

How to run:

```
# backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env   # fill keys
uvicorn app.main:app --reload --port 8000

# frontend
cd frontend && npm install && npm run dev
```

Open `http://localhost:5173`. Demo script:

1. “Compare Messi and Ronaldo” → card + spoken banter.
2. “Arsenal never bottled a title” → clapback with 2022-23 / Leicester facts.
3. “Commentate a 90th-minute bicycle kick winner” → roar SFX + dramatic call.

Document the 600 ms target and the env vars.

---

## 11. Implementation order

1. Protocol types both sides + FastAPI WS echo of `ping`/`audio_data`.
2. Frontend capture + playback + mic gate (loopback test optional via a debug flag `VITE_LOOPBACK=0` — do not leave loopback on).
3. Deepgram integration + transcript UI.
4. LLM + tools + `rivalries.json` + comparison card.
5. Cartesia + sentence flush + metrics HUD.
6. Barge-in both sides.
7. Mode switch + SFX.
8. Polish empty/error states; README.

---

## 12. Non-negotiable acceptance checks

- User talks; hears a relevant reply without pressing a button each turn.
- Spoken output is 1–2 sentences, no markdown.
- “Compare Messi and Ronaldo” or “Real Madrid vs Barca” → `lookup_head_to_head` + card + voice.
- “90th-minute bicycle kick” → `trigger_stadium_audio("stadium_roar")` + dramatic TTS.
- Speaking over the agent stops playback in < 100 ms locally and cancels the server turn.
- `metrics.total_turnaround_ms` displayed; aim < 600 on a warm connection.
- Missing vendor key → visible `error` in HUD, no process crash.
