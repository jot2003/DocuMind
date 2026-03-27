import cv2
import numpy as np

from backend.models.schemas import QualityResult


def assess_quality(image: np.ndarray) -> QualityResult:
    """Check image quality before processing. Reject blurry/dark/low-res images early."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    h, w = image.shape[:2]

    issues: list[str] = []
    if blur_score < 100:
        issues.append("Ảnh bị mờ. Vui lòng chụp lại rõ nét hơn.")
    if brightness < 40:
        issues.append("Ảnh quá tối. Vui lòng chụp ở nơi đủ sáng.")
    if brightness > 245:
        issues.append("Ảnh bị cháy sáng. Vui lòng tránh ánh sáng trực tiếp.")
    if min(h, w) < 200:
        issues.append("Độ phân giải quá thấp. Vui lòng chụp ảnh chất lượng cao hơn.")

    return QualityResult(
        passed=len(issues) == 0,
        blur_score=blur_score,
        brightness=brightness,
        resolution=(w, h),
        issues=issues,
    )
