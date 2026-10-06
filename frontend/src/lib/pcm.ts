export function pcm16ToFloat32(pcm: Int16Array): Float32Array {
  const out = new Float32Array(pcm.length)
  for (let i = 0; i < pcm.length; i += 1) {
    out[i] = pcm[i] < 0 ? pcm[i] / 0x8000 : pcm[i] / 0x7fff
  }
  return out
}

export function pcm16ToBase64(pcm: Int16Array): string {
  const bytes = new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength)
  let binary = ""
  const chunk = 0x8000
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk))
  }
  return btoa(binary)
}

export function base64ToPcm16(payload: string): Int16Array {
  const binary = atob(payload)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  const even = bytes.byteLength - (bytes.byteLength % 2)
  const copy = new ArrayBuffer(even)
  new Uint8Array(copy).set(bytes.subarray(0, even))
  return new Int16Array(copy)
}

export function resampleLinear(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate === toRate || input.length === 0) return input
  const outLength = Math.max(1, Math.round((input.length * toRate) / fromRate))
  const out = new Float32Array(outLength)
  const scale = fromRate / toRate
  const last = input.length - 1
  for (let i = 0; i < outLength; i += 1) {
    const position = i * scale
    const left = Math.floor(position)
    const right = Math.min(left + 1, last)
    const mix = position - left
    const a = input[Math.min(left, last)] ?? 0
    const b = input[right] ?? a
    out[i] = a * (1 - mix) + b * mix
  }
  return out
}

export function applyFadeIn(input: Float32Array, sampleRate: number, seconds = 0.005): Float32Array {
  const out = new Float32Array(input)
  const count = Math.min(out.length, Math.max(1, Math.round(sampleRate * seconds)))
  for (let i = 0; i < count; i += 1) out[i] *= i / count
  return out
}
