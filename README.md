# BanterBox

Live sports pundit you can talk to. One tap opens the mic, then the call is hands-free: duplex voice, a rivalry card, stadium stingers, and a latency HUD. Target time-to-first-audio is **under 600 ms** on a warm connection (`metrics.total_turnaround_ms`).

## Run

```
# backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env   # fill keys
uvicorn app.main:app --reload --port 8000

# frontend
cd frontend && npm install && npm run dev
```

Open `http://localhost:5173`. Python 3.12. The server still boots if a vendor key is missing and shows an `error` in the HUD the first time that vendor is used.

## Env

```
DEEPGRAM_API_KEY=
GEMINI_API_KEY=
CARTESIA_API_KEY=
CARTESIA_VOICE_DRAMATIC=
CARTESIA_VOICE_SPARRING=
CARTESIA_VOICE_ANALYST=
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
CORS_ORIGINS=http://localhost:5173
```

Empty Cartesia voice ids fall back to a Sonic English voice.

## Demo script

1. “Compare Messi and Ronaldo” → head-to-head card and spoken banter.
2. “Arsenal never bottled a title” → clapback with the 2022-23 lead and the Leicester season.
3. “Commentate a 90th-minute bicycle kick winner” → stadium roar and a dramatic call.

Talk over the reply to barge in. Playback stops locally; the server cancels that turn.

The build spec lives in [`BANTERBOX_IMPLEMENTATION_SPEC.md`](./BANTERBOX_IMPLEMENTATION_SPEC.md).
