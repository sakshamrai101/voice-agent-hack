import booUrl from "../assets/sfx/boo_crowd.wav"
import whistleUrl from "../assets/sfx/referee_whistle.wav"
import chantUrl from "../assets/sfx/siuuu_chant.wav"
import roarUrl from "../assets/sfx/stadium_roar.wav"

const FILES: Record<string, string> = {
  stadium_roar: roarUrl,
  referee_whistle: whistleUrl,
  boo_crowd: booUrl,
  siuuu_chant: chantUrl,
}

const cache = new Map<string, AudioBuffer>()
const SFX_GAIN = 0.45

export async function preloadSfx(context: AudioContext): Promise<void> {
  await Promise.all(
    Object.entries(FILES).map(async ([effect, url]) => {
      try {
        const response = await fetch(url)
        if (!response.ok) return
        const audio = await context.decodeAudioData(await response.arrayBuffer())
        cache.set(effect, audio)
      } catch {
        cache.delete(effect)
      }
    }),
  )
}

export function playSfx(context: AudioContext, effect: string): void {
  const gain = context.createGain()
  gain.gain.value = SFX_GAIN
  gain.connect(context.destination)
  const cached = cache.get(effect)
  if (cached) {
    const source = context.createBufferSource()
    source.buffer = cached
    source.connect(gain)
    source.start()
    return
  }
  synthesize(context, gain, effect)
}

function synthesize(context: AudioContext, gain: GainNode, effect: string): void {
  const now = context.currentTime
  if (effect === "stadium_roar" || effect === "boo_crowd") {
    const length = Math.floor(context.sampleRate * 1.2)
    const buffer = context.createBuffer(1, length, context.sampleRate)
    const data = buffer.getChannelData(0)
    for (let i = 0; i < length; i += 1) {
      const env = Math.sin((Math.PI * i) / length)
      const flutter = effect === "boo_crowd" ? 0.65 + 0.35 * Math.sin((i / context.sampleRate) * 18) : 1
      data[i] = (Math.random() * 2 - 1) * env * flutter * 0.8
    }
    const source = context.createBufferSource()
    source.buffer = buffer
    const filter = context.createBiquadFilter()
    filter.type = "lowpass"
    filter.frequency.value = effect === "boo_crowd" ? 500 : 900
    source.connect(filter)
    filter.connect(gain)
    source.start()
    return
  }

  const osc = context.createOscillator()
  osc.connect(gain)
  if (effect === "referee_whistle") {
    osc.type = "sine"
    osc.frequency.setValueAtTime(1700, now)
    osc.frequency.linearRampToValueAtTime(2100, now + 0.18)
    gain.gain.setValueAtTime(SFX_GAIN, now)
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.7)
    osc.start(now)
    osc.stop(now + 0.72)
    return
  }

  osc.type = "sawtooth"
  osc.frequency.setValueAtTime(220, now)
  osc.frequency.exponentialRampToValueAtTime(880, now + 0.85)
  gain.gain.setValueAtTime(SFX_GAIN, now)
  gain.gain.exponentialRampToValueAtTime(0.001, now + 1.1)
  osc.start(now)
  osc.stop(now + 1.12)
}
