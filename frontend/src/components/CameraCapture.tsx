import { useRef, useState, useEffect, useCallback } from 'react';
import { Camera, SwitchCamera, X, RotateCcw, Check } from 'lucide-react';

interface CameraCaptureProps {
  mode: 'document' | 'face';
  onCapture: (file: File) => void;
  onClose: () => void;
  label?: string;
}

const GUIDE_ASPECT = {
  document: 1.585, // ID card ~85.6x54mm
  face: 0.75,
};

const STABILITY_THRESHOLD = 12;
const STABILITY_FRAMES_NEEDED = 18;
const COUNTDOWN_FROM = 3;

export default function CameraCapture({ mode, onCapture, onClose, label }: CameraCaptureProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const prevFrameRef = useRef<ImageData | null>(null);
  const stableCountRef = useRef(0);
  const rafRef = useRef<number>(0);

  const [stream, setStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [facingMode, setFacingMode] = useState<'user' | 'environment'>(
    mode === 'face' ? 'user' : 'environment'
  );
  const [captured, setCaptured] = useState<string | null>(null);
  const [countdown, setCountdown] = useState<number | null>(null);
  const [isStable, setIsStable] = useState(false);
  const [detectionStatus, setDetectionStatus] = useState('');

  const countdownRef = useRef<number | null>(null);

  const startCamera = useCallback(async (facing: 'user' | 'environment') => {
    try {
      if (stream) {
        stream.getTracks().forEach((t) => t.stop());
      }

      const constraints: MediaStreamConstraints = {
        video: {
          facingMode: facing,
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
        audio: false,
      };

      const mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
      setStream(mediaStream);
      setError(null);

      if (videoRef.current) {
        videoRef.current.srcObject = mediaStream;
      }
    } catch {
      try {
        const fallback = await navigator.mediaDevices.getUserMedia({
          video: true,
          audio: false,
        });
        setStream(fallback);
        setError(null);
        if (videoRef.current) {
          videoRef.current.srcObject = fallback;
        }
      } catch {
        setError('Không thể truy cập camera. Vui lòng kiểm tra quyền truy cập.');
      }
    }
  }, [stream]);

  useEffect(() => {
    startCamera(facingMode);
    return () => {
      if (stream) {
        stream.getTracks().forEach((t) => t.stop());
      }
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      if (countdownRef.current) clearInterval(countdownRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!stream || captured) return;

    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return;

    let running = true;

    function analyzeFrame() {
      if (!running || !video || !canvas || !ctx) return;
      if (video.readyState < 2) {
        rafRef.current = requestAnimationFrame(analyzeFrame);
        return;
      }

      canvas.width = video.videoWidth / 4;
      canvas.height = video.videoHeight / 4;
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

      const frame = ctx.getImageData(0, 0, canvas.width, canvas.height);

      if (prevFrameRef.current && frame.data.length === prevFrameRef.current.data.length) {
        const diff = computeFrameDiff(prevFrameRef.current, frame);

        if (diff < STABILITY_THRESHOLD) {
          stableCountRef.current++;
        } else {
          stableCountRef.current = 0;
          if (countdownRef.current) {
            clearInterval(countdownRef.current);
            countdownRef.current = null;
            setCountdown(null);
          }
        }

        const stable = stableCountRef.current >= STABILITY_FRAMES_NEEDED;
        setIsStable(stable);

        if (mode === 'document') {
          const edgeScore = detectDocumentEdges(frame);
          if (stable && edgeScore > 0.3) {
            setDetectionStatus('Phát hiện tài liệu - Giữ nguyên');
            if (!countdownRef.current) {
              startCountdown();
            }
          } else if (stable) {
            setDetectionStatus('Giữ nguyên - Đang quét...');
          } else {
            setDetectionStatus('Đặt CCCD vào khung hướng dẫn');
          }
        } else {
          const hasFaceArea = detectFaceRegion(frame);
          if (stable && hasFaceArea) {
            setDetectionStatus('Phát hiện khuôn mặt - Giữ nguyên');
            if (!countdownRef.current) {
              startCountdown();
            }
          } else if (stable) {
            setDetectionStatus('Giữ nguyên - Đang quét...');
          } else {
            setDetectionStatus('Đưa khuôn mặt vào khung hướng dẫn');
          }
        }
      }

      prevFrameRef.current = frame;
      rafRef.current = requestAnimationFrame(analyzeFrame);
    }

    rafRef.current = requestAnimationFrame(analyzeFrame);

    return () => {
      running = false;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream, captured, mode]);

  function startCountdown() {
    let count = COUNTDOWN_FROM;
    setCountdown(count);

    countdownRef.current = window.setInterval(() => {
      count--;
      if (count <= 0) {
        clearInterval(countdownRef.current!);
        countdownRef.current = null;
        setCountdown(null);
        doCapture();
      } else {
        setCountdown(count);
      }
    }, 1000);
  }

  function doCapture() {
    const video = videoRef.current;
    if (!video) return;

    const captureCanvas = document.createElement('canvas');
    captureCanvas.width = video.videoWidth;
    captureCanvas.height = video.videoHeight;
    const ctx = captureCanvas.getContext('2d');
    if (!ctx) return;

    if (facingMode === 'user') {
      ctx.translate(captureCanvas.width, 0);
      ctx.scale(-1, 1);
    }
    ctx.drawImage(video, 0, 0);

    captureCanvas.toBlob(
      (blob) => {
        if (blob) {
          const url = URL.createObjectURL(blob);
          setCaptured(url);
          stableCountRef.current = 0;
          setIsStable(false);
        }
      },
      'image/jpeg',
      0.92
    );
  }

  function handleConfirm() {
    if (!captured) return;

    fetch(captured)
      .then((r) => r.blob())
      .then((blob) => {
        const file = new File([blob], `camera_${mode}_${Date.now()}.jpg`, {
          type: 'image/jpeg',
        });
        onCapture(file);
        cleanup();
      });
  }

  function handleRetake() {
    if (captured) URL.revokeObjectURL(captured);
    setCaptured(null);
    stableCountRef.current = 0;
    prevFrameRef.current = null;
    setIsStable(false);
    setCountdown(null);
    if (countdownRef.current) {
      clearInterval(countdownRef.current);
      countdownRef.current = null;
    }
  }

  function handleSwitchCamera() {
    const newFacing = facingMode === 'user' ? 'environment' : 'user';
    setFacingMode(newFacing);
    stableCountRef.current = 0;
    prevFrameRef.current = null;
    startCamera(newFacing);
  }

  function cleanup() {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    if (countdownRef.current) clearInterval(countdownRef.current);
  }

  function handleClose() {
    cleanup();
    onClose();
  }

  if (error) {
    return (
      <div className="bg-slate-900 rounded-2xl p-8 text-center">
        <div className="w-16 h-16 mx-auto mb-4 bg-red-500/10 rounded-full flex items-center justify-center">
          <Camera size={28} className="text-red-400" />
        </div>
        <p className="text-white font-medium mb-2">Camera không khả dụng</p>
        <p className="text-slate-400 text-sm mb-6">{error}</p>
        <button
          onClick={handleClose}
          className="px-4 py-2 bg-slate-700 text-white rounded-lg text-sm hover:bg-slate-600 transition-colors"
        >
          Đóng
        </button>
      </div>
    );
  }

  if (captured) {
    return (
      <div className="relative bg-slate-900 rounded-2xl overflow-hidden">
        <img src={captured} alt="Captured" className="w-full aspect-4/3 object-contain bg-black" />
        <div className="p-4 flex items-center justify-center gap-4">
          <button
            onClick={handleRetake}
            className="flex items-center gap-2 px-5 py-2.5 bg-slate-700 text-white rounded-lg text-sm font-medium hover:bg-slate-600 transition-colors"
          >
            <RotateCcw size={16} /> Chụp lại
          </button>
          <button
            onClick={handleConfirm}
            className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors shadow-lg shadow-blue-600/25"
          >
            <Check size={16} /> Sử dụng ảnh này
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="relative bg-slate-900 rounded-2xl overflow-hidden">
      <div className="relative aspect-4/3 overflow-hidden">
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className={`absolute inset-0 w-full h-full object-cover ${
            facingMode === 'user' ? 'scale-x-[-1]' : ''
          }`}
        />

        <canvas ref={canvasRef} className="hidden" />

        <GuideOverlay mode={mode} isStable={isStable} countdown={countdown} />

        {countdown !== null && (
          <div className="absolute inset-0 flex items-center justify-center z-20">
            <div className="w-24 h-24 rounded-full bg-white/20 backdrop-blur-sm flex items-center justify-center animate-pulse">
              <span className="text-5xl font-bold text-white drop-shadow-lg">{countdown}</span>
            </div>
          </div>
        )}

        <button
          onClick={handleClose}
          className="absolute top-3 right-3 z-30 w-9 h-9 bg-black/40 backdrop-blur-sm rounded-full flex items-center justify-center text-white hover:bg-black/60 transition-colors"
        >
          <X size={18} />
        </button>

        <div className="absolute bottom-3 left-3 right-3 z-20">
          <div className="bg-black/50 backdrop-blur-sm rounded-lg px-3 py-2">
            <p className="text-white text-xs text-center font-medium">
              {detectionStatus || (label ?? (mode === 'document' ? 'Đặt CCCD vào khung hướng dẫn' : 'Đưa khuôn mặt vào khung'))}
            </p>
          </div>
        </div>
      </div>

      <div className="p-3 flex items-center justify-center gap-6">
        <button
          onClick={handleSwitchCamera}
          className="w-10 h-10 bg-slate-700 rounded-full flex items-center justify-center text-white hover:bg-slate-600 transition-colors"
          title="Đổi camera"
        >
          <SwitchCamera size={18} />
        </button>

        <button
          onClick={doCapture}
          className="w-16 h-16 rounded-full border-4 border-white bg-white/10 hover:bg-white/30 transition-colors flex items-center justify-center group"
          title="Chụp thủ công"
        >
          <div className="w-12 h-12 rounded-full bg-white group-hover:scale-95 transition-transform" />
        </button>

        <div className="w-10 h-10" />
      </div>
    </div>
  );
}

function GuideOverlay({
  mode,
  isStable,
  countdown,
}: {
  mode: 'document' | 'face';
  isStable: boolean;
  countdown: number | null;
}) {
  const color = countdown !== null
    ? 'rgba(34, 197, 94, 0.9)'
    : isStable
      ? 'rgba(59, 130, 246, 0.8)'
      : 'rgba(255, 255, 255, 0.5)';

  const scanning = isStable && countdown === null;

  if (mode === 'document') {
    const w = 78;
    const h = w / GUIDE_ASPECT.document;
    const x = (100 - w) / 2;
    const y = (100 - h) / 2;

    return (
      <div className="absolute inset-0 z-10 pointer-events-none">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 w-full h-full">
          <defs>
            <mask id="doc-mask">
              <rect width="100" height="100" fill="white" />
              <rect x={x} y={y} width={w} height={h} rx="1.5" fill="black" />
            </mask>
          </defs>
          <rect width="100" height="100" fill="rgba(0,0,0,0.5)" mask="url(#doc-mask)" />
        </svg>

        <svg
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          className="absolute inset-0 w-full h-full"
        >
          <rect
            x={x} y={y} width={w} height={h}
            rx="1.5" fill="none"
            stroke={color}
            strokeWidth="0.4"
            className={countdown !== null ? 'animate-pulse' : ''}
          />

          {cornerMarks(x, y, w, h, color)}

          {scanning && (
            <line
              x1={x + 1} y1={y + 2}
              x2={x + w - 1} y2={y + 2}
              stroke="rgba(59, 130, 246, 0.6)"
              strokeWidth="0.3"
              className="animate-scan-doc"
            />
          )}
        </svg>

        {scanning && (
          <style>{`
            @keyframes scanDoc {
              0%, 100% { transform: translateY(0); }
              50% { transform: translateY(${h * 0.9}%); }
            }
            .animate-scan-doc { animation: scanDoc 2s ease-in-out infinite; }
          `}</style>
        )}
      </div>
    );
  }

  const cx = 50;
  const cy = 45;
  const rx = 18;
  const ry = rx / GUIDE_ASPECT.face;

  return (
    <div className="absolute inset-0 z-10 pointer-events-none">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 w-full h-full">
        <defs>
          <mask id="face-mask">
            <rect width="100" height="100" fill="white" />
            <ellipse cx={cx} cy={cy} rx={rx} ry={ry} fill="black" />
          </mask>
        </defs>
        <rect width="100" height="100" fill="rgba(0,0,0,0.5)" mask="url(#face-mask)" />
      </svg>

      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        className="absolute inset-0 w-full h-full"
      >
        <ellipse
          cx={cx} cy={cy} rx={rx} ry={ry}
          fill="none"
          stroke={color}
          strokeWidth="0.4"
          strokeDasharray={countdown !== null ? 'none' : '1 0.5'}
          className={countdown !== null ? 'animate-pulse' : ''}
        />

        {scanning && (
          <line
            x1={cx - rx + 2} y1={cy - ry + 3}
            x2={cx + rx - 2} y2={cy - ry + 3}
            stroke="rgba(59, 130, 246, 0.6)"
            strokeWidth="0.3"
            className="animate-scan-face"
          />
        )}
      </svg>

      {scanning && (
        <style>{`
          @keyframes scanFace {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(${ry * 1.8}%); }
          }
          .animate-scan-face { animation: scanFace 2s ease-in-out infinite; }
        `}</style>
      )}
    </div>
  );
}

function cornerMarks(x: number, y: number, w: number, h: number, color: string) {
  const len = 4;
  const sw = 0.6;
  return (
    <>
      <polyline points={`${x},${y+len} ${x},${y} ${x+len},${y}`} fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" />
      <polyline points={`${x+w-len},${y} ${x+w},${y} ${x+w},${y+len}`} fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" />
      <polyline points={`${x},${y+h-len} ${x},${y+h} ${x+len},${y+h}`} fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" />
      <polyline points={`${x+w-len},${y+h} ${x+w},${y+h} ${x+w},${y+h-len}`} fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" />
    </>
  );
}

function computeFrameDiff(prev: ImageData, curr: ImageData): number {
  const len = prev.data.length;
  let totalDiff = 0;
  const step = 16;

  for (let i = 0; i < len; i += step * 4) {
    totalDiff += Math.abs(prev.data[i] - curr.data[i]);
    totalDiff += Math.abs(prev.data[i + 1] - curr.data[i + 1]);
    totalDiff += Math.abs(prev.data[i + 2] - curr.data[i + 2]);
  }

  const samples = Math.floor(len / (step * 4));
  return totalDiff / (samples * 3);
}

function detectDocumentEdges(frame: ImageData): number {
  const w = frame.width;
  const h = frame.height;
  const data = frame.data;

  const guideX = Math.floor(w * 0.11);
  const guideY = Math.floor(h * 0.25);
  const guideW = Math.floor(w * 0.78);
  const guideH = Math.floor(h * 0.50);

  let edgePixels = 0;
  let totalChecked = 0;
  const threshold = 30;

  for (let side = 0; side < 4; side++) {
    let startX: number, startY: number, endX: number, endY: number;

    switch (side) {
      case 0: startX = guideX; startY = guideY; endX = guideX + guideW; endY = guideY; break;
      case 1: startX = guideX; startY = guideY + guideH; endX = guideX + guideW; endY = guideY + guideH; break;
      case 2: startX = guideX; startY = guideY; endX = guideX; endY = guideY + guideH; break;
      default: startX = guideX + guideW; startY = guideY; endX = guideX + guideW; endY = guideY + guideH; break;
    }

    const steps = Math.max(Math.abs(endX - startX), Math.abs(endY - startY));
    for (let s = 0; s < steps; s += 2) {
      const t = s / steps;
      const px = Math.floor(startX + (endX - startX) * t);
      const py = Math.floor(startY + (endY - startY) * t);

      if (px <= 1 || px >= w - 2 || py <= 1 || py >= h - 2) continue;

      const idx = (py * w + px) * 4;
      const gray = (data[idx] + data[idx + 1] + data[idx + 2]) / 3;

      const offset = side < 2 ? w * 4 : 4;
      const neighbor = (data[idx + offset] + data[idx + offset + 1] + data[idx + offset + 2]) / 3;

      if (Math.abs(gray - neighbor) > threshold) {
        edgePixels++;
      }
      totalChecked++;
    }
  }

  return totalChecked > 0 ? edgePixels / totalChecked : 0;
}

function detectFaceRegion(frame: ImageData): boolean {
  const w = frame.width;
  const h = frame.height;
  const data = frame.data;

  const cx = Math.floor(w * 0.5);
  const cy = Math.floor(h * 0.45);
  const rx = Math.floor(w * 0.18);
  const ry = Math.floor(h * 0.24);

  let skinPixels = 0;
  let totalChecked = 0;

  for (let y = cy - ry; y < cy + ry; y += 3) {
    for (let x = cx - rx; x < cx + rx; x += 3) {
      if (x < 0 || x >= w || y < 0 || y >= h) continue;

      const dx = (x - cx) / rx;
      const dy = (y - cy) / ry;
      if (dx * dx + dy * dy > 1) continue;

      const idx = (y * w + x) * 4;
      const r = data[idx];
      const g = data[idx + 1];
      const b = data[idx + 2];

      if (isSkinColor(r, g, b)) {
        skinPixels++;
      }
      totalChecked++;
    }
  }

  return totalChecked > 0 && skinPixels / totalChecked > 0.25;
}

function isSkinColor(r: number, g: number, b: number): boolean {
  return (
    r > 80 && g > 40 && b > 20 &&
    r > g && r > b &&
    Math.abs(r - g) > 15 &&
    r - b > 15
  );
}
