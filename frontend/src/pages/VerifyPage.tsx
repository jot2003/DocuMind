import { useState } from 'react';
import Stepper from '../components/Stepper';
import ImageDropzone from '../components/ImageDropzone';
import CameraCapture from '../components/CameraCapture';
import ResultView from '../components/ResultView';
import { verifyIdentity } from '../lib/api';
import {
  ArrowLeft,
  ArrowRight,
  SkipForward,
  ShieldCheck,
  RotateCcw,
  Plus,
  Upload,
  Camera,
} from 'lucide-react';

const EKYC_STEPS = [
  { label: 'CCCD Trước' },
  { label: 'CCCD Sau' },
  { label: 'Selfie' },
  { label: 'Xử lý' },
  { label: 'Kết quả' },
];

const PROCESSING_STEPS_FRONT_ONLY = [
  'Kiểm tra chất lượng ảnh',
  'Tiền xử lý ảnh',
  'Trích xuất OCR (mặt trước)',
  'Trích xuất VLM (mặt trước)',
  'Đối chiếu kết quả',
  'Xác minh khuôn mặt',
];

const PROCESSING_STEPS_WITH_BACK = [
  'Kiểm tra chất lượng ảnh',
  'Tiền xử lý ảnh',
  'Trích xuất OCR (mặt trước)',
  'Trích xuất VLM (mặt trước)',
  'Trích xuất mặt sau (OCR + VLM)',
  'Giải mã QR code',
  'Phân tích MRZ',
  'Đối chiếu đa nguồn',
  'Xác minh khuôn mặt',
];

export default function VerifyPage() {
  const [step, setStep] = useState(0);
  const [cccdFrontFile, setCccdFrontFile] = useState<File | null>(null);
  const [cccdBackFile, setCccdBackFile] = useState<File | null>(null);
  const [selfieFile, setSelfieFile] = useState<File | null>(null);
  const [processingStep, setProcessingStep] = useState(-1);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const [inputMode, setInputMode] = useState<'upload' | 'camera'>('upload');
  const [cameraOpen, setCameraOpen] = useState(false);

  const [frontPreview, setFrontPreview] = useState<string | null>(null);
  const [backPreview, setBackPreview] = useState<string | null>(null);
  const [selfiePreview, setSelfiePreview] = useState<string | null>(null);

  const activeProcessingSteps = cccdBackFile
    ? PROCESSING_STEPS_WITH_BACK
    : PROCESSING_STEPS_FRONT_ONLY;

  async function handleSubmit() {
    if (!cccdFrontFile || !selfieFile) return;

    setStep(3);
    setProcessingStep(0);
    setError(null);

    const steps = cccdBackFile ? PROCESSING_STEPS_WITH_BACK : PROCESSING_STEPS_FRONT_ONLY;
    const interval = cccdBackFile ? 2200 : 3000;

    const stepInterval = setInterval(() => {
      setProcessingStep((prev) => {
        if (prev >= steps.length - 1) {
          clearInterval(stepInterval);
          return prev;
        }
        return prev + 1;
      });
    }, interval);

    try {
      const res = await verifyIdentity(cccdFrontFile, selfieFile, cccdBackFile);
      clearInterval(stepInterval);
      setProcessingStep(steps.length - 1);

      if (res.status === 'quality_error') {
        setError(res.quality_issues?.join('\n') || 'Ảnh không đạt chất lượng.');
        return;
      }

      setResult(res);
      setTimeout(() => setStep(4), 600);
    } catch (err: any) {
      clearInterval(stepInterval);
      setError(
        err.response?.data?.detail || 'Có lỗi xảy ra. Vui lòng thử lại.'
      );
    }
  }

  function handleReset() {
    setStep(0);
    setCccdFrontFile(null);
    setCccdBackFile(null);
    setSelfieFile(null);
    setResult(null);
    setError(null);
    setProcessingStep(-1);
    setFrontPreview(null);
    setBackPreview(null);
    setSelfiePreview(null);
    setCameraOpen(false);
  }

  function handleCameraCapture(file: File, target: 'front' | 'back' | 'selfie') {
    const url = URL.createObjectURL(file);
    if (target === 'front') {
      setCccdFrontFile(file);
      setFrontPreview(url);
    } else if (target === 'back') {
      setCccdBackFile(file);
      setBackPreview(url);
    } else {
      setSelfieFile(file);
      setSelfiePreview(url);
    }
    setCameraOpen(false);
  }

  function handleFileSelect(file: File, target: 'front' | 'back' | 'selfie') {
    const url = URL.createObjectURL(file);
    if (target === 'front') {
      setCccdFrontFile(file);
      setFrontPreview(url);
    } else if (target === 'back') {
      setCccdBackFile(file);
      setBackPreview(url);
    } else {
      setSelfieFile(file);
      setSelfiePreview(url);
    }
  }

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <div className="mb-10">
        <Stepper steps={EKYC_STEPS} currentStep={step} />
      </div>

      {step === 0 && (
        <StepCard
          title="Ảnh CCCD mặt trước"
          subtitle="Chụp hoặc upload ảnh mặt trước căn cước công dân"
        >
          <InputModeTabs mode={inputMode} onChange={setInputMode} />

          {inputMode === 'upload' && (
            <ImageDropzone
              onFileSelect={(f) => handleFileSelect(f, 'front')}
              selectedFile={cccdFrontFile}
              label="Kéo thả ảnh CCCD mặt trước vào đây"
            />
          )}

          {inputMode === 'camera' && !cameraOpen && (
            <CameraStartButton
              preview={frontPreview}
              fileName={cccdFrontFile?.name}
              onOpen={() => setCameraOpen(true)}
              onClear={() => {
                setCccdFrontFile(null);
                setFrontPreview(null);
              }}
            />
          )}

          {inputMode === 'camera' && cameraOpen && (
            <CameraCapture
              mode="document"
              label="Đặt mặt trước CCCD vào khung hướng dẫn"
              onCapture={(f) => handleCameraCapture(f, 'front')}
              onClose={() => setCameraOpen(false)}
            />
          )}

          <StepActions>
            <div />
            <button
              onClick={() => setStep(1)}
              disabled={!cccdFrontFile}
              className="flex items-center gap-2 bg-blue-600 text-white px-6 py-2.5 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Tiếp tục <ArrowRight size={16} />
            </button>
          </StepActions>
        </StepCard>
      )}

      {step === 1 && (
        <StepCard
          title="Ảnh CCCD mặt sau"
          subtitle="Mặt sau chứa MRZ và QR code (tùy chọn)"
        >
          <InputModeTabs mode={inputMode} onChange={setInputMode} />

          {inputMode === 'upload' && (
            <ImageDropzone
              onFileSelect={(f) => handleFileSelect(f, 'back')}
              selectedFile={cccdBackFile}
              label="Kéo thả ảnh CCCD mặt sau vào đây"
            />
          )}

          {inputMode === 'camera' && !cameraOpen && (
            <CameraStartButton
              preview={backPreview}
              fileName={cccdBackFile?.name}
              onOpen={() => setCameraOpen(true)}
              onClear={() => {
                setCccdBackFile(null);
                setBackPreview(null);
              }}
            />
          )}

          {inputMode === 'camera' && cameraOpen && (
            <CameraCapture
              mode="document"
              label="Đặt mặt sau CCCD vào khung hướng dẫn"
              onCapture={(f) => handleCameraCapture(f, 'back')}
              onClose={() => setCameraOpen(false)}
            />
          )}

          <div className="mt-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
            <p className="text-xs text-blue-700">
              Hệ thống sẽ trích xuất thêm thông tin từ MRZ, QR code trên mặt sau
              để cross-check đa nguồn, tăng độ tin cậy. Bạn có thể bỏ qua nếu không có ảnh.
            </p>
          </div>
          <StepActions>
            <BackButton onClick={() => { setStep(0); setCameraOpen(false); }} />
            <div className="flex gap-3">
              <button
                onClick={() => { setStep(2); setCameraOpen(false); }}
                className="flex items-center gap-2 text-slate-500 hover:text-slate-900 text-sm font-medium transition-colors"
              >
                Bỏ qua <SkipForward size={16} />
              </button>
              {cccdBackFile && (
                <button
                  onClick={() => { setStep(2); setCameraOpen(false); }}
                  className="flex items-center gap-2 bg-blue-600 text-white px-6 py-2.5 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors"
                >
                  Tiếp tục <ArrowRight size={16} />
                </button>
              )}
            </div>
          </StepActions>
        </StepCard>
      )}

      {step === 2 && (
        <StepCard
          title="Ảnh selfie"
          subtitle="Chụp ảnh chân dung để so sánh với ảnh trên CCCD"
        >
          <InputModeTabs mode={inputMode} onChange={setInputMode} />

          {inputMode === 'upload' && (
            <ImageDropzone
              onFileSelect={(f) => handleFileSelect(f, 'selfie')}
              selectedFile={selfieFile}
              label="Kéo thả ảnh selfie vào đây"
            />
          )}

          {inputMode === 'camera' && !cameraOpen && (
            <CameraStartButton
              preview={selfiePreview}
              fileName={selfieFile?.name}
              onOpen={() => setCameraOpen(true)}
              onClear={() => {
                setSelfieFile(null);
                setSelfiePreview(null);
              }}
            />
          )}

          {inputMode === 'camera' && cameraOpen && (
            <CameraCapture
              mode="face"
              label="Đưa khuôn mặt vào khung hướng dẫn"
              onCapture={(f) => handleCameraCapture(f, 'selfie')}
              onClose={() => setCameraOpen(false)}
            />
          )}

          <div className="mt-4 bg-slate-50 rounded-lg p-4 border border-slate-100">
            <p className="text-xs font-medium text-slate-600 mb-2">Hướng dẫn</p>
            <ul className="space-y-1 text-xs text-slate-500">
              <li>Nhìn thẳng vào camera, đủ sáng</li>
              <li>Không đội mũ, không đeo kính râm</li>
              <li>Hỗ trợ PNG, JPG, WEBP - tối đa 10MB</li>
            </ul>
          </div>
          <StepActions>
            <BackButton onClick={() => { setStep(1); setCameraOpen(false); }} />
            <button
              onClick={handleSubmit}
              disabled={!selfieFile}
              className="flex items-center gap-2 bg-blue-600 text-white px-6 py-2.5 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-lg shadow-blue-600/20"
            >
              <ShieldCheck size={16} /> Xác minh
            </button>
          </StepActions>
        </StepCard>
      )}

      {step === 3 && (
        <StepCard
          title="Đang xử lý"
          subtitle="Hệ thống đang phân tích ảnh của bạn"
        >
          {error ? (
            <div>
              <div className="p-4 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700 whitespace-pre-line mb-6">
                {error}
              </div>
              <div className="flex justify-center">
                <button
                  onClick={handleReset}
                  className="flex items-center gap-2 bg-blue-600 text-white px-6 py-2.5 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors"
                >
                  <RotateCcw size={16} /> Thử lại
                </button>
              </div>
            </div>
          ) : (
            <div>
              <div className="space-y-3 max-w-md mx-auto">
                {activeProcessingSteps.map((s, i) => (
                  <div key={s} className="flex items-center gap-3">
                    <div className="w-5 h-5 flex items-center justify-center shrink-0">
                      {i < processingStep ? (
                        <span className="text-green-500 text-sm font-bold">
                          &#10003;
                        </span>
                      ) : i === processingStep ? (
                        <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                      ) : (
                        <div className="w-2.5 h-2.5 rounded-full bg-slate-200" />
                      )}
                    </div>
                    <span
                      className={`text-sm ${
                        i <= processingStep
                          ? 'text-slate-900'
                          : 'text-slate-400'
                      }`}
                    >
                      {s}
                    </span>
                  </div>
                ))}
              </div>
              <div className="mt-8">
                <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-600 rounded-full transition-all duration-500"
                    style={{
                      width: `${
                        ((processingStep + 1) / activeProcessingSteps.length) * 100
                      }%`,
                    }}
                  />
                </div>
                <p className="text-center text-xs text-slate-400 mt-2">
                  {Math.round(
                    ((processingStep + 1) / activeProcessingSteps.length) * 100
                  )}
                  %
                </p>
              </div>
            </div>
          )}
        </StepCard>
      )}

      {step === 4 && result && (
        <div>
          <ResultView result={result} />
          <div className="flex justify-center mt-8">
            <button
              onClick={handleReset}
              className="flex items-center gap-2 bg-blue-600 text-white px-6 py-2.5 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors"
            >
              <Plus size={16} /> Xác minh mới
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function InputModeTabs({
  mode,
  onChange,
}: {
  mode: 'upload' | 'camera';
  onChange: (m: 'upload' | 'camera') => void;
}) {
  return (
    <div className="flex gap-1 bg-slate-100 rounded-lg p-1 mb-4 w-fit">
      <button
        onClick={() => onChange('upload')}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
          mode === 'upload'
            ? 'bg-white text-slate-900 shadow-sm'
            : 'text-slate-500 hover:text-slate-700'
        }`}
      >
        <Upload size={14} /> Upload
      </button>
      <button
        onClick={() => onChange('camera')}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
          mode === 'camera'
            ? 'bg-white text-slate-900 shadow-sm'
            : 'text-slate-500 hover:text-slate-700'
        }`}
      >
        <Camera size={14} /> Camera
      </button>
    </div>
  );
}

function CameraStartButton({
  preview,
  fileName,
  onOpen,
  onClear,
}: {
  preview: string | null;
  fileName?: string;
  onOpen: () => void;
  onClear: () => void;
}) {
  if (preview) {
    return (
      <div className="border-2 border-green-300 bg-green-50/50 rounded-xl p-6 text-center min-h-[200px] flex items-center justify-center">
        <div className="space-y-3">
          <img
            src={preview}
            alt="Captured"
            className="max-h-36 mx-auto rounded-lg shadow-sm"
          />
          <p className="text-xs text-slate-500">{fileName}</p>
          <div className="flex gap-3 justify-center">
            <button
              onClick={onClear}
              className="text-xs text-slate-500 hover:text-red-600 transition-colors"
            >
              Xóa
            </button>
            <button
              onClick={onOpen}
              className="text-xs text-blue-600 hover:text-blue-800 font-medium transition-colors"
            >
              Chụp lại
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <button
      onClick={onOpen}
      className="w-full border-2 border-dashed border-slate-200 rounded-xl p-6 text-center min-h-[200px] flex items-center justify-center hover:border-blue-300 hover:bg-blue-50/30 transition-all group"
    >
      <div className="space-y-3">
        <div className="w-14 h-14 mx-auto bg-blue-50 group-hover:bg-blue-100 rounded-2xl flex items-center justify-center transition-colors">
          <Camera size={24} className="text-blue-500" />
        </div>
        <p className="text-sm font-medium text-slate-700">Mở camera để chụp</p>
        <p className="text-xs text-slate-400">
          Hệ thống sẽ tự động nhận diện và chụp khi ảnh ổn định
        </p>
      </div>
    </button>
  );
}

function StepCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white rounded-2xl border border-slate-200 p-8">
      <h2 className="text-lg font-semibold text-slate-900 mb-1">{title}</h2>
      <p className="text-sm text-slate-500 mb-6">{subtitle}</p>
      {children}
    </div>
  );
}

function StepActions({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between mt-6">{children}</div>
  );
}

function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-2 text-slate-500 hover:text-slate-900 text-sm font-medium transition-colors"
    >
      <ArrowLeft size={16} /> Quay lại
    </button>
  );
}
