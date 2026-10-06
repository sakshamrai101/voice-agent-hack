class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.pending = new Float32Array(0)
    this.read = 0
    this.reservoir = []
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (!channel || channel.length === 0) return true

    const merged = new Float32Array(this.pending.length + channel.length)
    merged.set(this.pending, 0)
    merged.set(channel, this.pending.length)

    const ratio = sampleRate / 16000
    let read = this.read
    const produced = []
    while (read + ratio <= merged.length) {
      const start = Math.floor(read)
      const end = Math.min(merged.length, Math.floor(read + ratio))
      let sum = 0
      let count = 0
      for (let i = start; i < end; i += 1) {
        sum += merged[i]
        count += 1
      }
      produced.push(count ? sum / count : 0)
      read += ratio
    }

    const keepFrom = Math.floor(read)
    this.pending = merged.slice(keepFrom)
    this.read = read - keepFrom
    this.reservoir.push(...produced)

    while (this.reservoir.length >= 320) {
      const frame = this.reservoir.splice(0, 320)
      const pcm = new Int16Array(320)
      let energy = 0
      for (let i = 0; i < 320; i += 1) {
        const sample = Math.max(-1, Math.min(1, frame[i]))
        energy += sample * sample
        pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff
      }
      const rms = Math.sqrt(energy / 320)
      this.port.postMessage({ type: "rms", value: rms })
      this.port.postMessage({ type: "pcm", pcm }, [pcm.buffer])
    }
    return true
  }
}

registerProcessor("pcm-processor", PCMProcessor)
