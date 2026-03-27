import time
import uuid
import logging
import traceback

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.models.database import get_db, VerificationRecord
from backend.models.schemas import VerifyResponse
from backend.services.image_quality import assess_quality
from backend.services.preprocessing import preprocess
from backend.services.ocr_service import OCRService
from backend.services.field_extractor import extract_cccd_fields
from backend.services.vlm_service import VLMService
from backend.services.cross_checker import cross_check
from backend.services.face_service import FaceService
from backend.utils.image_utils import read_image_from_bytes, save_upload
from backend.utils.config import UPLOAD_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["verification"])

_ocr_service: OCRService | None = None
_vlm_service: VLMService | None = None
_face_service: FaceService | None = None


def get_ocr() -> OCRService:
    global _ocr_service
    if _ocr_service is None:
        _ocr_service = OCRService()
    return _ocr_service


def get_vlm() -> VLMService:
    global _vlm_service
    if _vlm_service is None:
        _vlm_service = VLMService()
    return _vlm_service


def get_face() -> FaceService:
    global _face_service
    if _face_service is None:
        _face_service = FaceService()
    return _face_service


@router.post("/verify", response_model=VerifyResponse)
async def verify_identity(
    cccd_image: UploadFile = File(..., description="CCCD front image"),
    selfie_image: UploadFile = File(..., description="Selfie image"),
    db: Session = Depends(get_db),
):
    start = time.time()
    request_id = f"dm_{uuid.uuid4().hex[:12]}"

    cccd_bytes = await cccd_image.read()
    selfie_bytes = await selfie_image.read()

    try:
        cccd_img = read_image_from_bytes(cccd_bytes)
        selfie_img = read_image_from_bytes(selfie_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    cccd_quality = assess_quality(cccd_img)
    selfie_quality = assess_quality(selfie_img)

    all_issues = [f"[CCCD] {i}" for i in cccd_quality.issues] + \
                 [f"[Selfie] {i}" for i in selfie_quality.issues]

    if not cccd_quality.passed or not selfie_quality.passed:
        elapsed = (time.time() - start) * 1000
        record = VerificationRecord(
            id=request_id,
            status="quality_error",
            quality_issues=all_issues,
            processing_time_ms=elapsed,
        )
        db.add(record)
        db.commit()

        return VerifyResponse(
            request_id=request_id,
            status="quality_error",
            processing_time_ms=round(elapsed, 1),
            quality_issues=all_issues,
        )

    cccd_path = save_upload(cccd_bytes, UPLOAD_PATH, suffix=".jpg")
    selfie_path = save_upload(selfie_bytes, UPLOAD_PATH, suffix=".jpg")

    cccd_preprocessed = preprocess(cccd_img)

    try:
        ocr_svc = get_ocr()
        ocr_result = ocr_svc.extract(cccd_preprocessed)
        ocr_fields = extract_cccd_fields(ocr_result.full_text, ocr_result.lines)
        logger.info("[%s] OCR done: %d lines", request_id, len(ocr_result.lines))
    except Exception:
        logger.error("[%s] OCR failed:\n%s", request_id, traceback.format_exc())
        ocr_result = None
        ocr_fields = {}

    try:
        vlm_svc = get_vlm()
        vlm_fields = vlm_svc.extract_cccd(cccd_img)
        logger.info("[%s] VLM done", request_id)
    except Exception:
        logger.error("[%s] VLM failed:\n%s", request_id, traceback.format_exc())
        vlm_fields = {}

    cross_result = cross_check(ocr_fields, vlm_fields)
    logger.info("[%s] Cross-check: agreement=%.2f", request_id, cross_result.agreement)

    try:
        face_svc = get_face()
        face_result = face_svc.verify(cccd_img, selfie_img)
        logger.info("[%s] Face: %s (%.4f)", request_id, face_result.status, face_result.score)
    except Exception:
        logger.error("[%s] Face failed:\n%s", request_id, traceback.format_exc())
        from backend.models.schemas import FaceResult
        face_result = FaceResult(status="error", score=0.0)

    overall = _compute_overall(cross_result.agreement, face_result.score, face_result.status)

    ocr_bboxes_data = None
    if ocr_result:
        ocr_bboxes_data = [
            {"bbox": l.bbox, "text": l.text, "confidence": l.confidence}
            for l in ocr_result.lines
        ]

    elapsed = (time.time() - start) * 1000

    record = VerificationRecord(
        id=request_id,
        status="success",
        identity=cross_result.merged,
        ocr_result=ocr_fields,
        vlm_result=vlm_fields,
        merged_result=cross_result.merged,
        ocr_vlm_agreement=cross_result.agreement,
        face_score=face_result.score,
        face_status=face_result.status,
        overall_confidence=overall,
        quality_issues=all_issues if all_issues else None,
        ocr_bboxes=ocr_bboxes_data,
        processing_time_ms=elapsed,
        cccd_path=str(cccd_path),
        selfie_path=str(selfie_path),
    )
    db.add(record)
    db.commit()

    return VerifyResponse(
        request_id=request_id,
        status="success",
        identity=cross_result.merged,
        verification={
            "ocr_vlm_agreement": cross_result.agreement,
            "cross_check_details": [d.model_dump() for d in cross_result.details],
            "face_match": {"score": face_result.score, "status": face_result.status},
            "overall_confidence": overall,
        },
        sources={
            "ocr": ocr_fields,
            "vlm": vlm_fields,
        },
        processing_time_ms=round(elapsed, 1),
        ocr_bboxes=ocr_bboxes_data,
        quality_issues=all_issues if all_issues else None,
    )


def _compute_overall(agreement: float, face_score: float, face_status: str) -> float:
    field_weight = 0.6
    face_weight = 0.4

    face_component = face_score if face_status == "match" else 0.0
    return round(agreement * field_weight + face_component * face_weight, 4)


@router.get("/results/{request_id}", response_model=VerifyResponse)
async def get_result(request_id: str, db: Session = Depends(get_db)):
    record = db.query(VerificationRecord).filter_by(id=request_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Result not found")

    return VerifyResponse(
        request_id=record.id,
        status=record.status,
        identity=record.merged_result,
        verification={
            "ocr_vlm_agreement": record.ocr_vlm_agreement,
            "face_match": {"score": record.face_score, "status": record.face_status},
            "overall_confidence": record.overall_confidence,
        } if record.status == "success" else None,
        sources={
            "ocr": record.ocr_result,
            "vlm": record.vlm_result,
        } if record.status == "success" else None,
        processing_time_ms=record.processing_time_ms or 0,
        ocr_bboxes=record.ocr_bboxes,
        quality_issues=record.quality_issues,
    )


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "DocuMind eKYC API"}
