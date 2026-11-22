import { WS_URL } from "./api";
import type { ServerEvent } from "./types";

export type SocketStatus = "connecting" | "open" | "closed";

type Handlers = {
  onEvent: (ev: ServerEvent) => void;
  onBinary: (data: ArrayBuffer) => void;
  onStatus: (s: SocketStatus) => void;
  onUnauthorized: () => void;
};

/** Single WebSocket to the backend with exponential-backoff reconnect and keepalive pings. */
export class LokiSocket {
  private ws: WebSocket | null = null;
  private retry = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private stopped = false;

  constructor(private handlers: Handlers) {}

  connect() {
    this.stopped = false;
    this.handlers.onStatus("connecting");
    const ws = new WebSocket(WS_URL);
    ws.binaryType = "arraybuffer";
    this.ws = ws;

    ws.onopen = () => {
      this.retry = 0;
      this.handlers.onStatus("open");
      this.pingTimer = setInterval(() => this.send({ type: "ping" }), 25_000);
    };
    ws.onmessage = (msg) => {
      if (msg.data instanceof ArrayBuffer) {
        this.handlers.onBinary(msg.data);
        return;
      }
      try {
        this.handlers.onEvent(JSON.parse(msg.data) as ServerEvent);
      } catch {
        /* ignore malformed frames */
      }
    };
    ws.onclose = (ev) => {
      this.clearTimers();
      this.ws = null;
      this.handlers.onStatus("closed");
      if (ev.code === 4401) {
        this.handlers.onUnauthorized();
        return;
      }
      if (!this.stopped) {
        const delay = Math.min(30_000, 500 * 2 ** this.retry++);
        this.reconnectTimer = setTimeout(() => this.connect(), delay);
      }
    };
  }

  send(data: object): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(data));
    return true;
  }

  /** Sends a JSON header and its binary payload back-to-back. */
  sendWithBinary(header: object, payload: ArrayBuffer): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(header));
    this.ws.send(payload);
    return true;
  }

  close() {
    this.stopped = true;
    this.clearTimers();
    this.ws?.close();
    this.ws = null;
  }

  private clearTimers() {
    if (this.pingTimer) clearInterval(this.pingTimer);
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.pingTimer = this.reconnectTimer = null;
  }
}
