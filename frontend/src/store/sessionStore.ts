import { create } from "zustand"
import { isH2HCard, type AgentState, type ConnectionState, type H2HCard, type Mode, type ServerEvent } from "../lib/protocol"

export interface Bubble {
  id: string
  turnId: string
  role: "user" | "agent"
  text: string
  final: boolean
}

interface SessionState {
  connection: ConnectionState
  agentState: AgentState
  mode: Mode
  sessionId: string | null
  transcripts: Bubble[]
  card: H2HCard | null
  metrics: { stt: number | null; ttft: number | null; ttfa: number | null; rtt: number | null }
  errors: { code: string; message: string; recoverable: boolean }[]
  entered: boolean
  setConnection: (connection: ConnectionState) => void
  setEntered: (entered: boolean) => void
  setLocalError: (message: string) => void
  applyEvent: (event: ServerEvent) => void
}

function upsertError(
  current: SessionState["errors"],
  error: SessionState["errors"][number],
): SessionState["errors"] {
  const next = current.filter((item) => item.code !== error.code)
  next.push(error)
  return next.slice(-4)
}

function upsertTranscript(current: Bubble[], event: Extract<ServerEvent, { event: "transcript_stream" }>): Bubble[] {
  const next = current.slice()
  if (event.role === "user") {
    const open = next.findIndex((bubble) => bubble.role === "user" && !bubble.final)
    const bubble: Bubble = {
      id: `${event.turn_id}:user`,
      turnId: event.turn_id,
      role: "user",
      text: event.is_final && open >= 0 && !event.delta ? next[open].text : event.delta,
      final: event.is_final,
    }
    if (!event.is_final && open >= 0) bubble.text = event.delta
    if (open >= 0) next[open] = bubble
    else if (bubble.text) next.push(bubble)
    return next.slice(-40)
  }
  const index = next.findIndex((bubble) => bubble.role === "agent" && bubble.turnId === event.turn_id)
  if (index >= 0) {
    next[index] = {
      ...next[index],
      text: next[index].text + event.delta,
      final: event.is_final || next[index].final,
    }
    return next.slice(-40)
  }
  if (!event.delta && event.is_final) return next
  next.push({
    id: `${event.turn_id}:agent`,
    turnId: event.turn_id,
    role: "agent",
    text: event.delta,
    final: event.is_final,
  })
  return next.slice(-40)
}

export const useSessionStore = create<SessionState>((set) => ({
  connection: "down",
  agentState: "listening",
  mode: "pub_sparring_partner",
  sessionId: null,
  transcripts: [],
  card: null,
  metrics: { stt: null, ttft: null, ttfa: null, rtt: null },
  errors: [],
  entered: false,
  setConnection: (connection) => set({ connection }),
  setEntered: (entered) => set({ entered }),
  setLocalError: (message) =>
    set((state) => ({
      errors: upsertError(state.errors, { code: "SESSION_FATAL", message, recoverable: true }),
    })),
  applyEvent: (event) =>
    set((state) => {
      switch (event.event) {
        case "session_ready":
          return { sessionId: event.session_id, mode: event.mode, agentState: "listening" }
        case "agent_state":
          return { agentState: event.state }
        case "mode_changed":
          return { mode: event.mode }
        case "transcript_stream":
          return { transcripts: upsertTranscript(state.transcripts, event) }
        case "tool_executed":
          if (event.tool_name === "lookup_head_to_head" && isH2HCard(event.data)) {
            return { card: event.data }
          }
          return {}
        case "metrics":
          return {
            metrics: {
              ...state.metrics,
              stt: event.stt_final_ms,
              ttft: event.llm_ttft_ms,
              ttfa: event.total_turnaround_ms,
            },
          }
        case "pong":
          return { metrics: { ...state.metrics, rtt: Math.max(0, Date.now() - event.client_timestamp) } }
        case "error":
          return {
            errors: upsertError(state.errors, {
              code: event.code,
              message: event.message,
              recoverable: event.recoverable,
            }),
          }
        default:
          return {}
      }
    }),
}))
