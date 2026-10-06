export type Mode = "dramatic_commentator" | "pub_sparring_partner" | "data_analyst"
export type AgentState = "listening" | "thinking" | "speaking" | "interrupted"
export type ConnectionState = "live" | "reconnecting" | "down"

export type ToolName = "lookup_head_to_head" | "trigger_stadium_audio" | "switch_commentary_mode"

export type ErrorCode =
  | "STT_DISCONNECT"
  | "LLM_ERROR"
  | "TTS_ERROR"
  | "BAD_FRAME"
  | "TOOL_ERROR"
  | "SESSION_FATAL"

export interface EntitySide {
  name: string
  short: string
  accent: string
  stats: Record<string, string | number>
}

export interface H2HCard {
  sport: string
  entity_a: EntitySide
  entity_b: EntitySide
  h2h: { meetings: number; a_wins: number; b_wins: number; draws: number; label: string }
  banter_hook: string
  matched: boolean
}

export type ClientEvent =
  | { event: "audio_data"; payload: string; seq: number }
  | { event: "user_interrupted"; reason: "vad" | "manual"; client_timestamp: number }
  | { event: "ping"; client_timestamp: number }
  | { event: "client_ready"; sample_rate_in: number; sample_rate_out_preferred: number }

export type ServerEvent =
  | { event: "session_ready"; session_id: string; mode: Mode }
  | { event: "pong"; client_timestamp: number; server_timestamp: number }
  | { event: "agent_state"; state: AgentState }
  | { event: "transcript_stream"; role: "user" | "agent"; delta: string; is_final: boolean; turn_id: string }
  | { event: "tool_executed"; tool_name: ToolName; turn_id: string; data: Record<string, unknown> }
  | { event: "audio_output"; payload: string; sample_rate: number; turn_id: string; seq: number }
  | { event: "audio_output_end"; turn_id: string }
  | {
      event: "metrics"
      turn_id: string
      stt_final_ms: number
      llm_ttft_ms: number
      tts_ttfa_ms: number
      total_turnaround_ms: number
    }
  | { event: "error"; code: ErrorCode; message: string; recoverable: boolean; turn_id: string | null }
  | { event: "mode_changed"; mode: Mode }

const MODES: Mode[] = ["dramatic_commentator", "pub_sparring_partner", "data_analyst"]
const STATES: AgentState[] = ["listening", "thinking", "speaking", "interrupted"]
const TOOLS: ToolName[] = ["lookup_head_to_head", "trigger_stadium_audio", "switch_commentary_mode"]
const ERRORS: ErrorCode[] = ["STT_DISCONNECT", "LLM_ERROR", "TTS_ERROR", "BAD_FRAME", "TOOL_ERROR", "SESSION_FATAL"]

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

export function parseServerEvent(value: unknown): ServerEvent | null {
  if (!isRecord(value) || typeof value.event !== "string") return null
  switch (value.event) {
    case "session_ready":
      if (typeof value.session_id !== "string" || !MODES.includes(value.mode as Mode)) return null
      return { event: "session_ready", session_id: value.session_id, mode: value.mode as Mode }
    case "pong":
      if (typeof value.client_timestamp !== "number" || typeof value.server_timestamp !== "number") return null
      return { event: "pong", client_timestamp: value.client_timestamp, server_timestamp: value.server_timestamp }
    case "agent_state":
      if (!STATES.includes(value.state as AgentState)) return null
      return { event: "agent_state", state: value.state as AgentState }
    case "transcript_stream":
      if (
        (value.role !== "user" && value.role !== "agent") ||
        typeof value.delta !== "string" ||
        typeof value.is_final !== "boolean" ||
        typeof value.turn_id !== "string"
      ) {
        return null
      }
      return {
        event: "transcript_stream",
        role: value.role,
        delta: value.delta,
        is_final: value.is_final,
        turn_id: value.turn_id,
      }
    case "tool_executed":
      if (!TOOLS.includes(value.tool_name as ToolName) || typeof value.turn_id !== "string" || !isRecord(value.data)) {
        return null
      }
      return {
        event: "tool_executed",
        tool_name: value.tool_name as ToolName,
        turn_id: value.turn_id,
        data: value.data,
      }
    case "audio_output":
      if (
        typeof value.payload !== "string" ||
        typeof value.sample_rate !== "number" ||
        typeof value.turn_id !== "string" ||
        typeof value.seq !== "number"
      ) {
        return null
      }
      return {
        event: "audio_output",
        payload: value.payload,
        sample_rate: value.sample_rate,
        turn_id: value.turn_id,
        seq: value.seq,
      }
    case "audio_output_end":
      if (typeof value.turn_id !== "string") return null
      return { event: "audio_output_end", turn_id: value.turn_id }
    case "metrics":
      if (
        typeof value.turn_id !== "string" ||
        typeof value.stt_final_ms !== "number" ||
        typeof value.llm_ttft_ms !== "number" ||
        typeof value.tts_ttfa_ms !== "number" ||
        typeof value.total_turnaround_ms !== "number"
      ) {
        return null
      }
      return {
        event: "metrics",
        turn_id: value.turn_id,
        stt_final_ms: value.stt_final_ms,
        llm_ttft_ms: value.llm_ttft_ms,
        tts_ttfa_ms: value.tts_ttfa_ms,
        total_turnaround_ms: value.total_turnaround_ms,
      }
    case "error":
      if (!ERRORS.includes(value.code as ErrorCode) || typeof value.message !== "string" || typeof value.recoverable !== "boolean") {
        return null
      }
      return {
        event: "error",
        code: value.code as ErrorCode,
        message: value.message,
        recoverable: value.recoverable,
        turn_id: typeof value.turn_id === "string" ? value.turn_id : null,
      }
    case "mode_changed":
      if (!MODES.includes(value.mode as Mode)) return null
      return { event: "mode_changed", mode: value.mode as Mode }
    default:
      return null
  }
}

export function isH2HCard(data: Record<string, unknown>): data is H2HCard & Record<string, unknown> {
  return isRecord(data.entity_a) && isRecord(data.entity_b) && isRecord(data.h2h) && typeof data.banter_hook === "string"
}
