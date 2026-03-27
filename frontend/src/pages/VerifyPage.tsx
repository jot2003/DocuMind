import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ImageDropzone from '../components/ImageDropzone';
import { verifyIdentity } from '../lib/api';

const STEPS = [
  'Kiểm tra chất lượng ảnh',
  'Tiền xử lý ảnh',
  'Trích xuất OCR',
  'Trích xuất VLM',
  'Đối chiếu kết quả',
  'Xác minh khuôn mặt',
];

export default function VerifyPage() {
  const navigate = useNavigate();
  const [cccdFile, setCccdFile] = useState<File | null>(null);
  const [selfieFile, setSelfieFile] = useState<File | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [currentStep, setCurrentStep] = useState(-1);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = cccdFile && selfieFile && !isProcessing;

  async function handleVerify() {
    if (!cccdFile || !selfieFile) return;

    setIsProcessing(true);
    setError(null);
    setCurrentStep(0);

    const stepInterval = setInterval(() => {
      setCurrentStep((prev) => {
        if (prev >= STEPS.length - 1) {
          clearInterval(stepInterval);
          return prev;
        }
        return prev + 1;
      });
    }, 3000);

    try {
      const result = await verifyIdentity(cccdFile, selfieFile);
      clearInterval(stepInterval);
      setCurrentStep(STEPS.length - 1);

      if (result.status === 'quality_error') {
        setError(result.quality_issues?.join('\n') || 'Ảnh không đạt chất lượng.');
        setIsProcessing(false);
        setCurrentStep(-1);
        return;
      }

      setTimeout(() => {
        navigate(`/result/${result.request_id}`);
      }, 500);
    } catch (err: any) {
      clearInterval(stepInterval);
      setError(err.response?.data?.detail || 'Có lỗi xảy ra. Vui lòng thử lại.');
      setIsProcessing(false);
      setCurrentStep(-1);
    }
  }

  return (
    <main className="max-w-3xl mx-auto px-6 py-12">
      <h1 className="text-2xl font-bold text-slate-900 mb-2">Xác minh danh tính</h1>
      <p className="text-slate-500 mb-10">Upload ảnh CCCD mặt trước và ảnh selfie để bắt đầu.</p>

      {!isProcessing ? (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-3">
                Ảnh CCCD mặt trước
              </label>
              <ImageDropzone
                onFileSelect={setCccdFile}
                selectedFile={cccdFile}
                label="Kéo thả ảnh CCCD vào đây"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-3">
                Ảnh selfie
              </label>
              <ImageDropzone
                onFileSelect={setSelfieFile}
                selectedFile={selfieFile}
                label="Kéo thả ảnh selfie vào đây"
              />
            </div>
          </div>

          {/* Guidelines */}
          <details className="mb-8 bg-slate-50 rounded-xl p-5 border border-slate-100">
            <summary className="text-sm font-medium text-slate-600 cursor-pointer">
              Hướng dẫn chụp ảnh
            </summary>
            <ul className="mt-3 space-y-1.5 text-sm text-slate-500">
              <li>Đặt CCCD trên nền sáng màu, chụp thẳng từ trên xuống</li>
              <li>Ảnh không bị mờ, không bị cắt xén, không bị bóng đè</li>
              <li>Ảnh selfie nhìn thẳng, đủ sáng, không đội mũ/đeo kính râm</li>
              <li>Hỗ trợ PNG, JPG, WEBP - tối đa 10MB</li>
            </ul>
          </details>

          {error && (
            <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700 whitespace-pre-line">
              {error}
            </div>
          )}

          <button
            onClick={handleVerify}
            disabled={!canSubmit}
            className="w-full bg-blue-600 text-white py-3.5 rounded-xl text-base font-medium hover:bg-blue-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-blue-600/20"
          >
            Xác minh
          </button>
        </>
      ) : (
        /* Processing State */
        <div className="bg-white rounded-2xl p-10 border border-slate-100 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900 mb-8 text-center">Đang xử lý...</h2>
          <div className="space-y-4 max-w-md mx-auto">
            {STEPS.map((step, i) => (
              <div key={step} className="flex items-center gap-4">
                <div className="w-6 h-6 flex items-center justify-center">
                  {i < currentStep ? (
                    <span className="text-green-500 text-lg">&#10003;</span>
                  ) : i === currentStep ? (
                    <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                  ) : (
                    <div className="w-3 h-3 rounded-full bg-slate-200" />
                  )}
                </div>
                <span className={`text-sm ${i <= currentStep ? 'text-slate-900' : 'text-slate-400'}`}>
                  {step}
                </span>
              </div>
            ))}
          </div>
          <div className="mt-10">
            <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-600 rounded-full transition-all duration-500 ease-out"
                style={{ width: `${((currentStep + 1) / STEPS.length) * 100}%` }}
              />
            </div>
            <p className="text-center text-sm text-slate-400 mt-3">
              {Math.round(((currentStep + 1) / STEPS.length) * 100)}%
            </p>
          </div>
        </div>
      )}
    </main>
  );
}
