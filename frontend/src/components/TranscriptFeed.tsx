import { useEffect, useRef } from "react"
import { useSessionStore } from "../store/sessionStore"

export function TranscriptFeed() {
  const transcripts = useSessionStore((state) => state.transcripts)
  const scroller = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const node = scroller.current
    if (!node) return
    node.scrollTop = node.scrollHeight
  }, [transcripts])

  return (
    <section className="flex h-[min(68vh,640px)] flex-col rounded-2xl border border-white/10 bg-black/30">
      <header className="border-b border-white/10 px-4 py-3 text-[11px] uppercase tracking-[0.22em] text-white/50">
        Live transcript
      </header>
      <div ref={scroller} className="flex flex-1 flex-col gap-3 overflow-y-auto px-4 py-4">
        {transcripts.length === 0 ? (
          <p className="m-auto max-w-sm text-center text-sm text-white/40">
            Hands-free once you are in. Compare two sides, argue a bad take, or ask for a live call.
          </p>
        ) : (
          transcripts.map((bubble) => (
            <article
              key={bubble.id}
              className={
                bubble.role === "user"
                  ? "max-w-[90%] self-start rounded-2xl rounded-bl-sm bg-slate-800 px-4 py-3"
                  : "max-w-[90%] self-end rounded-2xl rounded-br-sm border border-amber-400/30 bg-amber-950/50 px-4 py-3 text-amber-50"
              }
            >
              <p className="mb-1 text-[10px] uppercase tracking-[0.18em] text-white/40">
                {bubble.role === "user" ? "You" : "BanterBox"}
              </p>
              <p className={bubble.role === "user" && !bubble.final ? "italic text-white/70" : "text-sm leading-relaxed"}>
                {bubble.text}
              </p>
            </article>
          ))
        )}
      </div>
    </section>
  )
}
