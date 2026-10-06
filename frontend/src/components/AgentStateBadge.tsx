import { Radio } from "lucide-react"
import { useSessionStore } from "../store/sessionStore"

const MODE_LABEL = {
  dramatic_commentator: "Dramatic",
  pub_sparring_partner: "Sparring",
  data_analyst: "Analyst",
} as const

const STATE_CLASS = {
  listening: "bg-[#0a7a3e]",
  thinking: "bg-amber-400",
  speaking: "bg-sky-400",
  interrupted: "bg-rose-500",
} as const

export function AgentStateBadge() {
  const agentState = useSessionStore((state) => state.agentState)
  const mode = useSessionStore((state) => state.mode)
  return (
    <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5">
      <Radio className="h-3.5 w-3.5 text-white/70" />
      <span className={`h-2 w-2 rounded-full ${STATE_CLASS[agentState]}`} />
      <span className="text-xs uppercase tracking-[0.18em] text-white/80">{agentState}</span>
      <span className="text-xs text-white/40">{MODE_LABEL[mode]}</span>
    </div>
  )
}
