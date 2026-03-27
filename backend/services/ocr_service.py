import logging
import re

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

from backend.models.schemas import OCRLine, OCRResult

logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 30
MIN_LINE_LEN = 2
TARGET_WIDTH = 2400
JUNK_RATIO_THRESHOLD = 0.6


class OCRService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        logger.info("Initializing Tesseract OCR (vie+eng)...")
        try:
            version = pytesseract.get_tesseract_version()
            logger.info("Tesseract version: %s", version)
        except Exception as e:
            logger.error("Tesseract not found: %s", e)
            raise RuntimeError("Tesseract is not installed or not in PATH") from e
        self._initialized = True
        logger.info("Tesseract OCR ready")

    def extract(self, image: np.ndarray) -> OCRResult:
        variants = self._make_variants(image)

        all_lines: list[OCRLine] = []
        for name, img in variants:
            for psm in [6, 3]:
                lines = self._run_tesseract(img, psm=psm)
                logger.debug("Variant %s PSM%d → %d lines", name, psm, len(lines))
                all_lines = self._merge_results(all_lines, lines)

        all_lines = self._filter_junk(all_lines)
        all_lines.sort(key=lambda l: (l.bbox[0][1], l.bbox[0][0]))
        full_text = "\n".join(l.text for l in all_lines)

        logger.info("OCR extracted %d lines, %d chars", len(all_lines), len(full_text))
        return OCRResult(lines=all_lines, full_text=full_text)

    def _make_variants(self, image: np.ndarray) -> list[tuple[str, np.ndarray]]:
        """Create multiple preprocessed versions for Tesseract."""
        upscaled = self._upscale(image)

        gray = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY)

        denoised = cv2.bilateralFilter(gray, 9, 75, 75)

        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced_gray = clahe.apply(denoised)

        _, otsu = cv2.threshold(enhanced_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        adaptive = cv2.adaptiveThreshold(
            enhanced_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 10,
        )

        sharp_kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]], dtype=np.float32) / 1.0
        sharpened = cv2.filter2D(enhanced_gray, -1, sharp_kernel)
        sharpened = np.clip(sharpened, 0, 255).astype(np.uint8)

        return [
            ("enhanced_gray", enhanced_gray),
            ("otsu", otsu),
            ("adaptive", adaptive),
            ("sharpened", sharpened),
        ]

    @staticmethod
    def _upscale(image: np.ndarray) -> np.ndarray:
        h, w = image.shape[:2]
        if w < TARGET_WIDTH:
            scale = TARGET_WIDTH / w
            image = cv2.resize(
                image, (int(w * scale), int(h * scale)),
                interpolation=cv2.INTER_CUBIC,
            )
        return image

    def _run_tesseract(self, image: np.ndarray, psm: int = 6) -> list[OCRLine]:
        if len(image.shape) == 3:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            rgb = image

        config = f"--psm {psm} --oem 1"
        data = pytesseract.image_to_data(
            rgb, lang="vie+eng", config=config, output_type=Output.DICT,
        )

        n = len(data["text"])
        line_groups: dict[tuple[int, int, int], list[int]] = {}

        for i in range(n):
            text = data["text"][i].strip()
            conf = int(data["conf"][i])
            if not text or conf < MIN_CONFIDENCE:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            if key not in line_groups:
                line_groups[key] = []
            line_groups[key].append(i)

        lines: list[OCRLine] = []
        for key in sorted(line_groups.keys()):
            indices = line_groups[key]
            words = []
            x_min, y_min = float("inf"), float("inf")
            x_max, y_max = 0.0, 0.0
            total_conf = 0.0

            for i in indices:
                words.append(data["text"][i])
                x = float(data["left"][i])
                y = float(data["top"][i])
                w = float(data["width"][i])
                h = float(data["height"][i])
                x_min = min(x_min, x)
                y_min = min(y_min, y)
                x_max = max(x_max, x + w)
                y_max = max(y_max, y + h)
                total_conf += float(data["conf"][i])

            line_text = " ".join(words)
            if len(line_text.strip()) < MIN_LINE_LEN:
                continue

            avg_conf = total_conf / len(indices) / 100.0
            bbox = [
                [x_min, y_min],
                [x_max, y_min],
                [x_max, y_max],
                [x_min, y_max],
            ]
            lines.append(OCRLine(bbox=bbox, text=line_text, confidence=avg_conf))

        return lines

    @staticmethod
    def _filter_junk(lines: list[OCRLine]) -> list[OCRLine]:
        """Remove lines that are mostly non-alphanumeric junk."""
        clean = []
        for line in lines:
            text = line.text.strip()
            if not text:
                continue
            alpha_count = sum(1 for c in text if c.isalnum() or c in "áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđÁÀẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬÉÈẺẼẸÊẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÚÙỦŨỤƯỨỪỬỮỰÝỲỶỸỴĐ/<>")
            total = len(text.replace(" ", ""))
            if total == 0:
                continue
            ratio = alpha_count / total
            if ratio >= JUNK_RATIO_THRESHOLD and len(text) >= MIN_LINE_LEN:
                clean.append(line)
            else:
                logger.debug("Filtered junk OCR line: '%s' (ratio=%.2f)", text[:50], ratio)
        return clean

    @staticmethod
    def _merge_results(existing: list[OCRLine], new_lines: list[OCRLine]) -> list[OCRLine]:
        if not existing:
            return list(new_lines)
        if not new_lines:
            return existing

        merged = list(existing)
        for nline in new_lines:
            best_match_idx = -1
            best_iou = 0.0
            for idx, mline in enumerate(merged):
                iou = _bbox_iou(mline.bbox, nline.bbox)
                if iou > best_iou:
                    best_iou = iou
                    best_match_idx = idx

            if best_iou > 0.3 and best_match_idx >= 0:
                old = merged[best_match_idx]
                if nline.confidence > old.confidence or (
                    nline.confidence >= old.confidence * 0.9
                    and len(nline.text) > len(old.text)
                ):
                    merged[best_match_idx] = nline
            else:
                merged.append(nline)
        return merged


def _bbox_iou(bbox1: list[list[float]], bbox2: list[list[float]]) -> float:
    x1_min, y1_min = bbox1[0]
    x1_max, y1_max = bbox1[2]
    x2_min, y2_min = bbox2[0]
    x2_max, y2_max = bbox2[2]

    inter_x = max(0, min(x1_max, x2_max) - max(x1_min, x2_min))
    inter_y = max(0, min(y1_max, y2_max) - max(y1_min, y2_min))
    inter_area = inter_x * inter_y

    area1 = (x1_max - x1_min) * (y1_max - y1_min)
    area2 = (x2_max - x2_min) * (y2_max - y2_min)
    union_area = area1 + area2 - inter_area

    return inter_area / union_area if union_area > 0 else 0.0
