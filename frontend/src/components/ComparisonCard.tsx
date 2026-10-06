import { useSessionStore } from "../store/sessionStore"

export function ComparisonCard() {
  const card = useSessionStore((state) => state.card)
  if (!card) {
    return (
      <section className="flex h-[min(68vh,640px)] items-center justify-center rounded-2xl border border-dashed border-white/15 bg-black/20 px-6 text-center text-white/50">
        Waiting for a rivalry…
      </section>
    )
  }

  const keys = Object.keys(card.entity_a.stats).slice(0, 4)
  const total = Math.max(1, card.h2h.a_wins + card.h2h.b_wins + card.h2h.draws)
  const aWidth = `${(card.h2h.a_wins / total) * 100}%`
  const drawWidth = `${(card.h2h.draws / total) * 100}%`
  const bWidth = `${(card.h2h.b_wins / total) * 100}%`

  return (
    <section className="flex h-[min(68vh,640px)] flex-col overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-b from-white/[0.06] to-black/40">
      <header className="flex items-center justify-between px-4 py-3 text-[11px] uppercase tracking-[0.22em] text-white/50">
        <span>{card.sport}</span>
        <span>{card.matched ? "Archive" : "Mock split"}</span>
      </header>
      <div className="grid grid-cols-[1fr_auto_1fr] items-stretch gap-2 px-4">
        <div className="rounded-xl bg-black/30 p-3" style={{ boxShadow: `inset 0 3px 0 ${card.entity_a.accent}` }}>
          <p className="text-2xl font-semibold" style={{ color: card.entity_a.accent }}>
            {card.entity_a.short}
          </p>
          <p className="text-xs text-white/50">{card.entity_a.name}</p>
        </div>
        <div className="flex items-center text-[11px] tracking-[0.2em] text-white/35">VS</div>
        <div className="rounded-xl bg-black/30 p-3 text-right" style={{ boxShadow: `inset 0 3px 0 ${card.entity_b.accent}` }}>
          <p className="text-2xl font-semibold" style={{ color: card.entity_b.accent }}>
            {card.entity_b.short}
          </p>
          <p className="text-xs text-white/50">{card.entity_b.name}</p>
        </div>
      </div>
      <div className="mt-4 grid flex-1 grid-cols-1 content-start gap-2 px-4 sm:grid-cols-2">
        {keys.map((key) => (
          <div key={key} className="grid grid-cols-[auto_1fr_auto] items-center gap-2 rounded-lg bg-black/40 px-3 py-2 text-sm">
            <span className="font-mono tabular-nums" style={{ color: card.entity_a.accent }}>
              {String(card.entity_a.stats[key] ?? "—")}
            </span>
            <span className="truncate text-center text-[11px] uppercase tracking-wider text-white/45">{key}</span>
            <span className="font-mono tabular-nums" style={{ color: card.entity_b.accent }}>
              {String(card.entity_b.stats[key] ?? "—")}
            </span>
          </div>
        ))}
      </div>
      <div className="px-4 pb-4">
        <div className="mb-1 flex justify-between text-[10px] uppercase tracking-[0.14em] text-white/40">
          <span>
            {card.h2h.a_wins} wins
          </span>
          <span>{card.h2h.label}</span>
          <span>{card.h2h.b_wins} wins</span>
        </div>
        <div className="flex h-2 overflow-hidden rounded-full bg-white/10">
          <span style={{ width: aWidth, background: card.entity_a.accent }} />
          <span style={{ width: drawWidth }} className="bg-white/30" />
          <span style={{ width: bWidth, background: card.entity_b.accent }} />
        </div>
        <p className="mt-3 rounded-lg bg-[#0a7a3e]/20 px-3 py-2 text-sm leading-snug text-emerald-50">{card.banter_hook}</p>
      </div>
    </section>
  )
}
