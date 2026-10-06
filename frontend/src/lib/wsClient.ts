import { AudioCapture, BARGE_IN_RMS } from "./audioCapture"
import { AudioPlayback } from "./audioPlayback"
import { pcm16ToBase64, pcm16ToFloat32, resampleLinear } from "./pcm"
import { type ClientEvent, parseServerEvent, type ServerEvent } from "./protocol"
import { playSfx, preloadSfx } from "./sfx"
import { useSessionStore } from "../store/sessionStore"

const WS_URL = import.meta.env.VITE_WS_URL ?? "ws://localhost:8000/ws/voice"
const LOOPBACK = import.meta.env.VITE_LOOPBACK === "1"
const BACKOFF_MS = [200, 500, 1000, 2000, 5000]

export class VoiceSocket {
  private ws: WebSocket | null = null
  private attempt = 0
  private timer = 0
  private pingTimer = 0
  private stopped = false
  seq = 0

  constructor(
    private readonly onEvent: (event: ServerEvent) => void,
    private readonly onStatus: (status: "live" | "reconnecting" | "down") => void,
  ) {}

  connect(): void {
    this.stopped = false
    this.open()
  }

  stop(): void {
    this.stopped = true
    window.clearTimeout(this.timer)
    window.clearInterval(this.pingTimer)
    this.ws?.close()
    this.ws = null
    this.onStatus("down")
  }

  get isOpen(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  send(event: ClientEvent): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(event))
  }

  sendAudio(pcm: Int16Array): void {
    this.send({ event: "audio_data", payload: pcm16ToBase64(pcm), seq: this.seq })
    this.seq += 1
  }

  private open(): void {
    if (this.stopped) return
    this.onStatus("reconnecting")
    const ws = new WebSocket(WS_URL)
    this.ws = ws
    ws.onopen = () => {
      this.attempt = 0
      this.seq = 0
      this.onStatus("live")
      this.send({ event: "client_ready", sample_rate_in: 16000, sample_rate_out_preferred: 24000 })
      window.clearInterval(this.pingTimer)
      this.pingTimer = window.setInterval(() => {
        this.send({ event: "ping", client_timestamp: Date.now() })
      }, 10000)
    }
    ws.onmessage = (message) => {
      let parsed: unknown
      try {
        parsed = JSON.parse(String(message.data))
      } catch {
        return
      }
      const event = parseServerEvent(parsed)
      if (event) this.onEvent(event)
    }
    ws.onclose = () => {
      window.clearInterval(this.pingTimer)
      if (this.stopped) {
        this.onStatus("down")
        return
      }
      const delay = BACKOFF_MS[Math.min(this.attempt, BACKOFF_MS.length - 1)] ?? 5000
      this.attempt += 1
      this.onStatus("reconnecting")
      this.timer = window.setTimeout(() => this.open(), delay)
    }
    ws.onerror = () => {
      ws.close()
    }
  }
}

export interface VoiceHandle {
  stop: () => void
}

export async function startVoice(): Promise<VoiceHandle> {
  const playback = new AudioPlayback()
  const resumePromise = playback.resume()
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  })
  await resumePromise
  void preloadSfx(playback.context)

  let liveTurn: string | null = null
  let hotFrames = 0
  let armed = true
  const prebuffer: Int16Array[] = []

  const socket = new VoiceSocket(
    (event) => {
      if (event.event === "transcript_stream" && event.role === "user" && event.is_final) {
        liveTurn = event.turn_id
      }
      if (event.event === "agent_state" && event.state === "interrupted") {
        playback.flush()
        liveTurn = null
        armed = true
        hotFrames = 0
      }
      if (event.event === "audio_output") {
        if (liveTurn !== null && event.turn_id === liveTurn) playback.enqueueBase64(event.payload)
        return
      }
      if (event.event === "audio_output_end") playback.markTurnEnded()
      if (event.event === "tool_executed" && event.tool_name === "trigger_stadium_audio") {
        const effect = event.data.effect
        if (typeof effect === "string") playSfx(playback.context, effect)
      }
      useSessionStore.getState().applyEvent(event)
    },
    (status) => {
      useSessionStore.getState().setConnection(status)
      if (status === "live" && prebuffer.length) {
        for (const frame of prebuffer) socket.sendAudio(frame)
        prebuffer.length = 0
      }
    },
  )

  const capture = new AudioCapture(
    (pcm) => {
      if (LOOPBACK) {
        const floats = pcm16ToFloat32(pcm)
        playback.enqueueFloat(
          playback.context.sampleRate === 16000 ? floats : resampleLinear(floats, 16000, playback.context.sampleRate),
        )
      }
      if (socket.isOpen) socket.sendAudio(pcm)
      else if (prebuffer.length < 50) prebuffer.push(pcm)
    },
    (rms) => {
      const playing = playback.isPlaying()
      if (!playing) {
        hotFrames = 0
        armed = true
        return
      }
      if (!armed) return
      if (rms > BARGE_IN_RMS) {
        hotFrames += 1
        if (hotFrames >= 3) {
          armed = false
          hotFrames = 0
          playback.flush()
          liveTurn = null
          useSessionStore.getState().applyEvent({ event: "agent_state", state: "interrupted" })
          socket.send({ event: "user_interrupted", reason: "vad", client_timestamp: Date.now() })
        }
        return
      }
      hotFrames = 0
    },
  )

  socket.connect()
  await capture.start(stream)
  useSessionStore.getState().setEntered(true)

  return {
    stop() {
      socket.stop()
      capture.stop()
      playback.flush()
    },
  }
}
