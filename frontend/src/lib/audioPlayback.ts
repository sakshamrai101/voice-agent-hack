import { applyFadeIn, base64ToPcm16, pcm16ToFloat32, resampleLinear } from "./pcm"

const TARGET_RATE = 24000

export class AudioPlayback {
  readonly context: AudioContext
  private master: GainNode
  private sources = new Set<AudioBufferSourceNode>()
  private pending: Float32Array[] = []
  private nextStartTime = 0
  private queuedMs = 0
  private primed = false
  private firstOfTurn = true
  private turnOpen = false
  private playing = false

  constructor() {
    this.context = new AudioContext({ sampleRate: TARGET_RATE })
    this.master = this.context.createGain()
    this.master.connect(this.context.destination)
  }

  async resume(): Promise<void> {
    if (this.context.state !== "running") await this.context.resume()
  }

  isPlaying(): boolean {
    return this.playing
  }

  enqueueBase64(payload: string): void {
    const pcm = base64ToPcm16(payload)
    let floats = pcm16ToFloat32(pcm)
    if (this.context.sampleRate !== TARGET_RATE) {
      floats = resampleLinear(floats, TARGET_RATE, this.context.sampleRate)
    }
    this.enqueueFloat(floats)
  }

  enqueueFloat(floats: Float32Array): void {
    if (!this.turnOpen) {
      this.turnOpen = true
      this.firstOfTurn = true
      if (this.sources.size === 0) {
        this.primed = false
        this.nextStartTime = 0
        this.queuedMs = 0
        this.pending = []
      }
    }
    this.pending.push(floats)
    this.queuedMs += (floats.length / this.context.sampleRate) * 1000
    if (!this.primed) {
      if (this.queuedMs >= 60 || this.pending.length >= 3) {
        this.primed = true
        this.drain()
      }
      return
    }
    this.drain()
  }

  markTurnEnded(): void {
    this.turnOpen = false
  }

  flush(): void {
    const now = this.context.currentTime
    this.master.gain.cancelScheduledValues(now)
    this.master.gain.setValueAtTime(this.master.gain.value, now)
    this.master.gain.linearRampToValueAtTime(0, now + 0.005)
    this.master.gain.setValueAtTime(1, now + 0.008)
    const stopAt = now + 0.005
    for (const source of this.sources) {
      try {
        source.stop(stopAt)
      } catch {
        /* already stopped */
      }
    }
    this.sources.clear()
    this.pending = []
    this.nextStartTime = 0
    this.queuedMs = 0
    this.primed = false
    this.firstOfTurn = true
    this.turnOpen = false
    this.playing = false
  }

  private drain(): void {
    while (this.pending.length > 0) {
      const next = this.pending.shift()
      if (!next) break
      this.queuedMs = Math.max(0, this.queuedMs - (next.length / this.context.sampleRate) * 1000)
      const now = this.context.currentTime
      if (this.nextStartTime !== 0 && this.nextStartTime - now < 0.01 && this.pending.length === 0) {
        const silence = new Float32Array(Math.round(0.02 * this.context.sampleRate))
        this.schedule(silence, false)
      }
      const fade = this.firstOfTurn
      this.firstOfTurn = false
      this.schedule(fade ? applyFadeIn(next, this.context.sampleRate) : next, true)
    }
  }

  private schedule(data: Float32Array, audible: boolean): void {
    const buffer = this.context.createBuffer(1, data.length, this.context.sampleRate)
    buffer.copyToChannel(new Float32Array(data), 0)
    const source = this.context.createBufferSource()
    source.buffer = buffer
    source.connect(this.master)
    const when =
      this.nextStartTime === 0
        ? this.context.currentTime + 0.02
        : Math.max(this.context.currentTime + 0.02, this.nextStartTime)
    source.start(when)
    this.nextStartTime = when + buffer.duration
    this.sources.add(source)
    if (audible) this.playing = true
    source.onended = () => {
      this.sources.delete(source)
      if (this.sources.size === 0 && this.pending.length === 0) this.playing = false
    }
  }
}
