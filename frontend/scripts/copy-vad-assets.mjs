// Copies the voice-activity-detection model, audio worklet and ONNX runtime WASM into public/vad,
// so they are served by this app (no third-party CDN at runtime).
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "public", "vad");
mkdirSync(out, { recursive: true });

const vad = join(root, "node_modules", "@ricky0123", "vad-web", "dist");
const ort = join(root, "node_modules", "onnxruntime-web", "dist");
const files = [
  [vad, "silero_vad_v5.onnx"],
  [vad, "vad.worklet.bundle.min.js"],
  [ort, "ort-wasm-simd-threaded.wasm"],
  [ort, "ort-wasm-simd-threaded.mjs"],
  [ort, "ort-wasm-simd-threaded.jsep.wasm"],
  [ort, "ort-wasm-simd-threaded.jsep.mjs"],
];
for (const [dir, name] of files) copyFileSync(join(dir, name), join(out, name));
console.log(`copied ${files.length} VAD assets to public/vad`);
