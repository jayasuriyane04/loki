/**
 * Real activity signal for the visualiser, read every animation frame without React re-renders.
 * Phase 1: bumped by actual streamed tokens. Phase 2 will feed microphone / TTS amplitude (0..1) here.
 * Nothing in here is synthetic: with no input the level decays to zero.
 */
let level = 0;
let lastUpdate = 0;

export const energy = {
  bump(amount = 0.35) {
    level = Math.min(1, level + amount);
    lastUpdate = performance.now();
  },
  setAmplitude(value: number) {
    level = Math.max(0, Math.min(1, value));
    lastUpdate = performance.now();
  },
  /** Current level with exponential decay since the last real input. */
  read(now = performance.now()) {
    const dt = (now - lastUpdate) / 1000;
    return level * Math.exp(-dt * 4);
  },
};
