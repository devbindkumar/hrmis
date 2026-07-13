// Shared face-capture hook that wraps @vladmandic/human for the browser.
// Handles:
//   • Loading models lazily from the vendor CDN (offline once cached)
//   • Requesting webcam permission (fails fast with a friendly message)
//   • Running the detect loop
//   • Exposing the latest embedding + liveness + antispoof scores + face box
// The hook is deliberately un-opinionated so both the kiosk scanner and the
// admin enrollment UI can share it.

import { useEffect, useRef, useState, useCallback } from "react";

// Model CDN — @vladmandic ships all weights here. Cached by the browser.
const MODEL_BASE = "https://cdn.jsdelivr.net/npm/@vladmandic/human@3.3.6/models/";
// tfjs-wasm SIMD/threaded binaries — served from jsdelivr so we don't rely on
// the SPA to serve `.wasm` files (which would 404 → HTML → CompileError).
const WASM_BASE = "https://cdn.jsdelivr.net/npm/@tensorflow/tfjs-backend-wasm@4.22.0/dist/";

// Human config — humangl is our primary backend (a hardened WebGL wrapper),
// WASM is the fallback for browsers without WebGL. `cpu` is the last-ditch
// fallback and is slow but always works.
const HUMAN_CONFIG = {
  modelBasePath: MODEL_BASE,
  wasmPath: WASM_BASE,
  backend: "humangl",
  cacheSensitivity: 0,
  warmup: "none",
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
      try {
        const mod = await import("@vladmandic/human");
        const H = mod.Human || mod.default;
        const h = new H(HUMAN_CONFIG);
        try {
          await h.load();
        } catch (loadErr) {
          // If humangl fails (rare — no GPU / disabled WebGL), retry with WASM
          console.warn("[face] humangl load failed, retrying with wasm:", loadErr);
          h.config.backend = "wasm";
          await h.load();
        }
        humanInstance = h;
        return h;
      } catch (err) {
        // reset so a retry can try again
        humanReady = null;
        throw err;
      }
    })();
  }
  return humanReady;
}

function friendlyMediaError(e) {
  const name = e?.name || "";
  if (name === "NotAllowedError" || name === "PermissionDeniedError") {
    return "Camera permission denied. Click the camera icon in the browser address bar and allow camera access, then try again.";
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError") {
    return "No camera found on this device. Connect a webcam and try again.";
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return "Camera is in use by another app. Close other apps using the webcam and try again.";
  }
  if (name === "OverconstrainedError") {
    return "This webcam does not support the requested resolution. Try a different device.";
  }
  if (name === "SecurityError" || String(e?.message || "").includes("secure context")) {
    return "Camera requires a secure (HTTPS) page. Open this URL over HTTPS.";
  }
  return e?.message || "Unable to start the camera.";
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
  const [retryTick, setRetryTick] = useState(0);
  const [state, setState] = useState({
    detected: false,
    embedding: null,
    live: 0,
    real: 0,
    box: null,
    score: 0,
  });

  const retry = useCallback(() => {
    setError(null);
    setReady(false);
    setLoadingModels(true);
    setRetryTick((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    let human;

    const start = async () => {
      // Secure-context guard — webcams require https (or localhost). If we
      // catch this early we can show a proper message instead of a spinner.
      if (typeof window !== "undefined" && !window.isSecureContext) {
        setError("Camera access requires HTTPS. Open the page over HTTPS and try again.");
        setLoadingModels(false);
        return;
      }
      if (!navigator?.mediaDevices?.getUserMedia) {
        setError("This browser doesn't support webcam access. Please use Chrome, Edge or Firefox.");
        setLoadingModels(false);
        return;
      }

      // 1) Request the webcam FIRST so a permission-denial fails fast (before
      //    downloading 15 MB of models).
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false,
        });
      } catch (e) {
        setError(friendlyMediaError(e));
        setLoadingModels(false);
        return;
      }
      if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        try { await videoRef.current.play(); } catch { /* autoplay */ }
      }

      // 2) Load Human + models
      try {
        setLoadingModels(true);
        human = await loadHuman();
      } catch (e) {
        console.error("[face] model load failed", e);
        setError(
          "Face-recognition models failed to load. Check your internet connection and click Retry. " +
          "If this persists, your browser may not support WebGL or WebAssembly."
        );
        setLoadingModels(false);
        return;
      }
      if (cancelled) return;
      setLoadingModels(false);
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
    };
    start();
    return () => {
      cancelled = true;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
  }, [enabled, retryTick]);

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

  return { videoRef, canvasRef, ready, loadingModels, error, state, captureJpeg, retry };
}
