import type { MicVAD } from "@ricky0123/vad-web";
import { rms } from "./audio";
import { energy } from "./energy";

type MicHandlers = {
  /** Confirmed speech (passed the minimum-length check) — used for barge-in. */
  onSpeechStart: () => void;
  /** One finished utterance, mono float32 at 16 kHz. */
  onUtterance: (audio: Float32Array) => void;
  onHearing: (hearing: boolean) => void;
};

/**
 * Microphone + Silero voice-activity detection running locally in the browser.
 * Only finished utterances leave the page; silence and background audio are never sent.
 */
export class MicInput {
  private vad: MicVAD | null = null;

  constructor(private h: MicHandlers) {}

  async start() {
    if (this.vad) {
      await this.vad.start();
      return;
    }
    const { MicVAD } = await import("@ricky0123/vad-web");
    this.vad = await MicVAD.new({
      model: "v5",
      baseAssetPath: "/vad/",
      onnxWASMBasePath: "/vad/",
      positiveSpeechThreshold: 0.6,
      negativeSpeechThreshold: 0.4,
      redemptionMs: 700, // pause length that ends a turn
      preSpeechPadMs: 300,
      minSpeechMs: 250,
      startOnLoad: false,
      onSpeechStart: () => this.h.onHearing(true),
      onSpeechRealStart: () => this.h.onSpeechStart(),
      onVADMisfire: () => this.h.onHearing(false),
      onSpeechEnd: (audio) => {
        this.h.onHearing(false);
        this.h.onUtterance(audio);
      },
      onFrameProcessed: (_probs, frame) => {
        energy.setAmplitude(Math.min(1, rms(frame) * 6));
      },
    });
    await this.vad.start();
  }

  async pause() {
    await this.vad?.pause();
    this.h.onHearing(false);
  }

  async destroy() {
    await this.vad?.destroy();
    this.vad = null;
  }
}

export function describeMicError(e: unknown): string {
  const name = (e as { name?: string })?.name;
  if (name === "NotAllowedError") return "Microphone permission was denied. Allow it in the browser's site settings.";
  if (name === "NotFoundError") return "No microphone was found.";
  if (name === "NotReadableError") return "The microphone is in use by another application.";
  return `Couldn't start the microphone: ${(e as Error)?.message ?? String(e)}`;
}
