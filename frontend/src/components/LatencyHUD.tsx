import { Gauge } from "lucide-react"
import { useSessionStore } from "../store/sessionStore"

function Stat({ label, value, hot }: { label: string; value: number | null; hot?: boolean }) {
  const text = value === null ? "—" : `${value}`
  const tone = hot && value !== null ? (value < 600 ? "text-emerald-300" : "text-amber-300") : "text-white"
  return (
    <div className="flex flex-col items-end leading-none">
      <span className="text-[11px] uppercase tracking-[0.16em] text-white/55">{label}</span>
      <span className={`mt-1 font-mono text-sm tabular-nums ${tone}`}>{text}</span>
    </div>
  )
}

export function LatencyHUD() {
  const metrics = useSessionStore((state) => state.metrics)
  return (
    <div className="flex items-center gap-3">
      <Gauge className="h-4 w-4 text-[#0a7a3e]" />
      <Stat label="STT" value={metrics.stt} />
      <Stat label="TTFT" value={metrics.ttft} />
      <Stat label="TTFA" value={metrics.ttfa} hot />
      <Stat label="RTT" value={metrics.rtt} />
    </div>
  )
}

export function ErrorStrip() {
  const errors = useSessionStore((state) => state.errors)
  if (errors.length === 0) return null
  return (
    <div className="mt-3 flex flex-col items-end gap-1">
      {errors.map((error) => (
        <p key={error.code} className={`text-xs ${error.recoverable ? "text-amber-300" : "text-rose-300"}`}>
          {error.code}: {error.message}
        </p>
      ))}
    </div>
  )
}
