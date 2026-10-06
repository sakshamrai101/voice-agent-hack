import { Swords } from "lucide-react"
import { AgentStateBadge } from "./components/AgentStateBadge"
import { ComparisonCard } from "./components/ComparisonCard"
import { ErrorStrip, LatencyHUD } from "./components/LatencyHUD"
import { MicGate } from "./components/MicGate"
import { TranscriptFeed } from "./components/TranscriptFeed"
import { useSessionStore } from "./store/sessionStore"

const PILL = {
  live: "bg-emerald-400",
  reconnecting: "bg-amber-300",
  down: "bg-rose-400",
} as const

export default function App() {
  const connection = useSessionStore((state) => state.connection)
  return (
    <div className="min-h-screen bg-[#07090d] text-slate-100">
      <div className="mx-auto flex min-h-screen w-full max-w-[1280px] flex-col px-4 py-4 md:px-6">
        <header className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <Swords className="h-5 w-5 text-[#0a7a3e]" />
            <span className="text-lg font-semibold tracking-[0.28em]">BANTERBOX</span>
          </div>
          <div className="inline-flex items-center gap-2 rounded-full border border-white/10 px-3 py-1 text-[11px] uppercase tracking-[0.16em] text-white/70">
            <span className={`h-2 w-2 rounded-full ${PILL[connection]}`} />
            {connection}
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-4">
            <AgentStateBadge />
            <LatencyHUD />
          </div>
        </header>
        <div className="mt-4 h-px bg-gradient-to-r from-[#0a7a3e] via-[#0a7a3e]/40 to-transparent" />
        <ErrorStrip />
        <main className="mt-4 grid flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
          <TranscriptFeed />
          <ComparisonCard />
        </main>
        <MicGate />
      </div>
    </div>
  )
}
