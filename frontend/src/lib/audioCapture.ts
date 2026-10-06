import workletSource from "../worklets/pcm-processor.js?raw"

export const BARGE_IN_RMS = 0.025

type FrameHandler = (pcm: Int16Array) => void
type RmsHandler = (rms: number) => void

export class AudioCapture {
  private context: AudioContext | null = null
  private stream: MediaStream | null = null

  constructor(
    private readonly onFrame: FrameHandler,
    private readonly onRms: RmsHandler,
  ) {}

  async start(stream: MediaStream): Promise<void> {
    this.stream = stream
    const context = new AudioContext()
    this.context = context
    if (context.state !== "running") await context.resume()
    const workletUrl = URL.createObjectURL(new Blob([workletSource], { type: "text/javascript" }))
    try {
      await context.audioWorklet.addModule(workletUrl)
    } finally {
      URL.revokeObjectURL(workletUrl)
    }
    const source = context.createMediaStreamSource(stream)
    const node = new AudioWorkletNode(context, "pcm-processor")
    node.port.onmessage = (event: MessageEvent<{ type: string; pcm?: Int16Array; value?: number }>) => {
      if (event.data.type === "pcm" && event.data.pcm) this.onFrame(event.data.pcm)
      if (event.data.type === "rms" && typeof event.data.value === "number") this.onRms(event.data.value)
    }
    const mute = context.createGain()
    mute.gain.value = 0
    source.connect(node)
    node.connect(mute)
    mute.connect(context.destination)
  }

  stop(): void {
    this.stream?.getTracks().forEach((track) => track.stop())
    void this.context?.close()
    this.stream = null
    this.context = null
  }
}
