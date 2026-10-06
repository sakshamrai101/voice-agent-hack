import { useRef, useState } from "react"
import { Mic } from "lucide-react"
import { startVoice, type VoiceHandle } from "../lib/wsClient"
import { useSessionStore } from "../store/sessionStore"

export function MicGate() {
  const entered = useSessionStore((state) => state.entered)
  const agentState = useSessionStore((state) => state.agentState)
  const connection = useSessionStore((state) => state.connection)
  const setLocalError = useSessionStore((state) => state.setLocalError)
  const handle = useRef<VoiceHandle | null>(null)
  const [busy, setBusy] = useState(false)

  async function enter() {
    if (busy || entered) return
    setBusy(true)
    try {
      handle.current = await startVoice()
    } catch (error) {
      const message = error instanceof Error ? error.message : "Microphone permission failed"
      setLocalError(message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-4 flex items-center justify-between gap-4">
      <p className="text-[11px] uppercase tracking-[0.18em] text-white/35">{connection}</p>
      {entered ? (
        <div className="relative flex h-20 w-20 items-center justify-center">
          {agentState === "listening" ? (
            <span className="absolute inset-0 animate-ping rounded-full bg-[#0a7a3e]/40" />
          ) : null}
          <div className="relative flex h-16 w-16 items-center justify-center rounded-full border border-[#0a7a3e]/60 bg-[#0a7a3e]/20">
            {agentState === "speaking" ? <LevelBars /> : <Mic className="h-6 w-6 text-emerald-200" />}
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => void enter()}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-full bg-[#0a7a3e] px-5 py-3 text-sm font-semibold tracking-wide text-white disabled:opacity-60"
        >
          <Mic className="h-4 w-4" />
          {busy ? "Opening the box…" : "Tap to enter the box"}
        </button>
      )}
      <p className="text-[11px] uppercase tracking-[0.18em] text-white/35">
        {entered ? "Hands free" : "Mic gate"}
      </p>
    </div>
  )
}

function LevelBars() {
  return (
    <div className="flex h-7 items-end gap-1">
      {[0, 1, 2, 3, 4].map((index) => (
        <span
          key={index}
          className="w-1 origin-bottom rounded-full bg-emerald-200"
          style={{ height: "100%", animation: `banter-bar 0.8s ${index * 0.1}s ease-in-out infinite` }}
        />
      ))}
    </div>
  )
}
