import { energy } from "./energy";

/**
 * Plays LOKI's streamed speech: int16 PCM chunks scheduled back-to-back on one AudioContext.
 * An AnalyserNode measures the real output level for the visualiser.
 */
export class SpeechPlayer {
  private ctx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private gain: GainNode | null = null;
  private sources = new Set<AudioBufferSourceNode>();
  private nextTime = 0;
  private raf = 0;
  private levelBuf: Float32Array<ArrayBuffer> | null = null;
  playing = false;

  constructor(private onPlayingChange: (playing: boolean) => void) {}

  /** Must be called from a user gesture (click) so the browser allows audio. */
  async unlock() {
    if (!this.ctx) {
      this.ctx = new AudioContext();
      this.gain = this.ctx.createGain();
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 512;
      this.levelBuf = new Float32Array(this.analyser.fftSize);
      this.gain.connect(this.analyser);
      this.analyser.connect(this.ctx.destination);
    }
    if (this.ctx.state === "suspended") await this.ctx.resume();
  }

  enqueue(pcm: ArrayBuffer, sampleRate: number) {
    if (!this.ctx || !this.gain) return;
    const int16 = new Int16Array(pcm);
    if (int16.length === 0) return;
    const buffer = this.ctx.createBuffer(1, int16.length, sampleRate);
    const ch = buffer.getChannelData(0);
    for (let i = 0; i < int16.length; i++) ch[i] = int16[i] / 32768;

    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.gain);
    const start = Math.max(this.ctx.currentTime + 0.03, this.nextTime);
    src.start(start);
    this.nextTime = start + buffer.duration;
    this.sources.add(src);
    src.onended = () => {
      this.sources.delete(src);
      if (this.sources.size === 0) this.setPlaying(false);
    };
    this.setPlaying(true);
  }

  /** Barge-in / stop: silence immediately and drop everything queued. */
  stop() {
    for (const s of this.sources) {
      s.onended = null;
      try {
        s.stop();
      } catch {
        /* already stopped */
      }
    }
    this.sources.clear();
    this.nextTime = 0;
    this.setPlaying(false);
  }

  private setPlaying(p: boolean) {
    if (p === this.playing) return;
    this.playing = p;
    this.onPlayingChange(p);
    if (p) this.meter();
    else cancelAnimationFrame(this.raf);
  }

  private meter = () => {
    if (!this.analyser || !this.levelBuf) return;
    this.analyser.getFloatTimeDomainData(this.levelBuf);
    energy.setAmplitude(Math.min(1, rms(this.levelBuf) * 4));
    this.raf = requestAnimationFrame(this.meter);
  };
}

export function rms(buf: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
  return Math.sqrt(sum / buf.length);
}

/** Float32 [-1,1] → little-endian int16 PCM bytes. */
export function floatToPcm16(audio: Float32Array): ArrayBuffer {
  const out = new Int16Array(audio.length);
  for (let i = 0; i < audio.length; i++) {
    const s = Math.max(-1, Math.min(1, audio[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out.buffer;
}
