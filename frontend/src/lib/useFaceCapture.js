// Shared face-capture hook that wraps @vladmandic/human for the browser.
// Handles:
//   • Loading models lazily from the vendor CDN (offline once cached)
//   • Requesting webcam permission
//   • Running the detect loop
//   • Exposing the latest embedding + liveness + antispoof scores + face box
// The hook is deliberately un-opinionated so both the kiosk scanner and the
// admin enrollment UI can share it.

import { useEffect, useRef, useState } from "react";

// Model CDN — @vladmandic ships all weights here. Cached by the browser.
const MODEL_BASE = "https://cdn.jsdelivr.net/npm/@vladmandic/human/models/";

const HUMAN_CONFIG = {
  modelBasePath: MODEL_BASE,
  cacheSensitivity: 0,
  filter: { enabled: true, equalization: true },
  face: {
    enabled: true,
    detector: { rotation: false, maxDetected: 1, minConfidence: 0.6, return: false },
    description: { enabled: true },   // ArcFace 128-d embedding
    iris: { enabled: false },
    emotion: { enabled: false },
    antispoof: { enabled: true },     // real vs fake
    liveness: { enabled: true },      // depth / 3D vs 2D
  },
  body:  { enabled: false },
  hand:  { enabled: false },
  object:{ enabled: false },
  gesture:{ enabled: false },
};

let humanInstance = null;
let humanReady = null;

async function loadHuman() {
  if (humanInstance) return humanInstance;
  if (!humanReady) {
    humanReady = (async () => {
      const mod = await import("@vladmandic/human");
      const H = mod.Human || mod.default;
      const h = new H(HUMAN_CONFIG);
      await h.load();
      await h.warmup();
      humanInstance = h;
      return h;
    })();
  }
  return humanReady;
}

/**
 * useFaceCapture — attach a webcam stream to a <video ref> and expose the
 * latest face embedding + liveness scores. The consumer decides when to
 * "sample" (freeze the current embedding).
 */
export default function useFaceCapture({ enabled = true } = {}) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const rafRef = useRef(0);
  const streamRef = useRef(null);
  const [ready, setReady] = useState(false);
  const [loadingModels, setLoadingModels] = useState(true);
  const [error, setError] = useState(null);
  const [state, setState] = useState({
    detected: false,
    embedding: null,
    live: 0,
    real: 0,
    box: null,
    score: 0,
  });

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    let human;

    const start = async () => {
      try {
        setLoadingModels(true);
        human = await loadHuman();
        if (cancelled) return;
        setLoadingModels(false);

        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false,
        });
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }
        setReady(true);

        const loop = async () => {
          if (cancelled || !videoRef.current) return;
          try {
            const result = await human.detect(videoRef.current);
            const f = result?.face?.[0];
            if (f && f.embedding) {
              setState({
                detected: true,
                embedding: Array.from(f.embedding),
                live: typeof f.live === "number" ? f.live : 0,
                real: typeof f.real === "number" ? f.real : 0,
                box: f.box || null,
                score: f.score || 0,
              });
            } else {
              setState((s) => (s.detected ? { ...s, detected: false } : s));
            }
          } catch (e) {
            // swallow — some frames may fail
          }
          rafRef.current = requestAnimationFrame(loop);
        };
        loop();
      } catch (e) {
        setError(e.message || "Camera / model load failed");
        setLoadingModels(false);
      }
    };
    start();
    return () => {
      cancelled = true;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop());
    };
  }, [enabled]);

  // Capture the current frame as a JPEG base64 (for admin enrollment)
  const captureJpeg = () => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return null;
    const c = canvasRef.current || document.createElement("canvas");
    canvasRef.current = c;
    c.width = video.videoWidth;
    c.height = video.videoHeight;
    const ctx = c.getContext("2d");
    ctx.drawImage(video, 0, 0);
    return c.toDataURL("image/jpeg", 0.85);
  };

  return { videoRef, canvasRef, ready, loadingModels, error, state, captureJpeg };
}
