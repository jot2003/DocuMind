import time
import uuid
import logging
import traceback

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.database import get_db, VerificationRecord
from backend.models.schemas import VerifyResponse
from backend.services.image_quality import assess_quality
from backend.services.preprocessing import preprocess
from backend.services.ocr_service import OCRService
from backend.services.field_extractor import extract_cccd_fields, extract_cccd_back_fields
from backend.services.vlm_service import VLMService
from backend.services.cross_checker import cross_check
from backend.services.face_service import FaceService
from backend.services.qr_service import decode_qr
from backend.services.mrz_service import parse_mrz
from backend.services.card_detector import detect_and_crop_card
from backend.services.doc_classifier import classify_document
from backend.services.liveness_service import verify_liveness
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
    cccd_back_image: UploadFile | None = File(None, description="CCCD back image (optional)"),
    db: Session = Depends(get_db),
):
    start = time.time()
    request_id = f"dm_{uuid.uuid4().hex[:12]}"

    cccd_bytes = await cccd_image.read()
    selfie_bytes = await selfie_image.read()
    cccd_back_bytes = await cccd_back_image.read() if cccd_back_image else None

    try:
        cccd_img = read_image_from_bytes(cccd_bytes)
        selfie_img = read_image_from_bytes(selfie_bytes)
        cccd_back_img = read_image_from_bytes(cccd_back_bytes) if cccd_back_bytes else None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    cccd_quality = assess_quality(cccd_img)
    selfie_quality = assess_quality(selfie_img)
    all_issues = [f"[CCCD] {i}" for i in cccd_quality.issues] + \
                 [f"[Selfie] {i}" for i in selfie_quality.issues]

    back_quality_ok = True
    if cccd_back_img is not None:
        back_quality = assess_quality(cccd_back_img)
        all_issues += [f"[CCCD_Back] {i}" for i in back_quality.issues]
        if not back_quality.passed:
            back_quality_ok = False
            logger.warning("[%s] Back image quality failed, will skip back processing", request_id)

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
    cccd_back_path_str = None
    if cccd_back_bytes:
        cccd_back_path = save_upload(cccd_back_bytes, UPLOAD_PATH, suffix=".jpg")
        cccd_back_path_str = str(cccd_back_path)

    # --- Card detection & cropping ---
    cccd_cropped = detect_and_crop_card(cccd_img)
    logger.info("[%s] Front card cropped: %dx%d -> %dx%d",
                request_id,
                cccd_img.shape[1], cccd_img.shape[0],
                cccd_cropped.shape[1], cccd_cropped.shape[0])

    cccd_preprocessed = preprocess(cccd_cropped)

    # --- Front side: OCR + VLM ---
    try:
        ocr_svc = get_ocr()
        ocr_result = ocr_svc.extract(cccd_cropped)
        ocr_fields = extract_cccd_fields(ocr_result.full_text, ocr_result.lines)
        logger.info("[%s] OCR front done: %d lines, text=%s",
                    request_id, len(ocr_result.lines), ocr_result.full_text[:200])
    except Exception:
        logger.error("[%s] OCR front failed:\n%s", request_id, traceback.format_exc())
        ocr_result = None
        ocr_fields = {}

    try:
        vlm_svc = get_vlm()
        vlm_fields = vlm_svc.extract_cccd(cccd_cropped)
        logger.info("[%s] VLM front done", request_id)
    except Exception:
        logger.error("[%s] VLM front failed:\n%s", request_id, traceback.format_exc())
        vlm_fields = {}

    # --- Back side: OCR + VLM + QR + MRZ ---
    qr_fields = None
    mrz_fields = None
    ocr_back_fields = {}
    vlm_back_fields = {}

    if cccd_back_img is not None:
        if not back_quality_ok:
            logger.warning("[%s] Back image quality low, processing anyway (VLM may handle it)", request_id)

        cccd_back_cropped = detect_and_crop_card(cccd_back_img)
        logger.info("[%s] Back card cropped: %dx%d -> %dx%d",
                    request_id,
                    cccd_back_img.shape[1], cccd_back_img.shape[0],
                    cccd_back_cropped.shape[1], cccd_back_cropped.shape[0])

        back_preprocessed = preprocess(cccd_back_cropped)

        try:
            ocr_back_result = ocr_svc.extract(cccd_back_cropped)
            ocr_back_fields = extract_cccd_back_fields(
                ocr_back_result.full_text, ocr_back_result.lines
            )
            logger.info("[%s] OCR back done: %d lines, text=%s",
                        request_id, len(ocr_back_result.lines),
                        ocr_back_result.full_text[:200])

            mrz_fields = parse_mrz(ocr_back_result.full_text)
            if mrz_fields:
                logger.info("[%s] MRZ parsed: %d fields", request_id,
                            sum(1 for v in mrz_fields.values() if v))
        except Exception:
            logger.error("[%s] OCR/MRZ back failed:\n%s", request_id, traceback.format_exc())

        try:
            vlm_back_fields = vlm_svc.extract_cccd_back(cccd_back_cropped)
            logger.info("[%s] VLM back done: %s",
                        request_id, {k: v for k, v in vlm_back_fields.items() if v})

            if vlm_back_fields.get("mrz_line_1") and not mrz_fields:
                mrz_text = "\n".join(filter(None, [
                    vlm_back_fields.get("mrz_line_1"),
                    vlm_back_fields.get("mrz_line_2"),
                    vlm_back_fields.get("mrz_line_3"),
                ]))
                mrz_fields = parse_mrz(mrz_text)
                if mrz_fields:
                    logger.info("[%s] MRZ parsed from VLM lines", request_id)
        except Exception:
            logger.error("[%s] VLM back failed:\n%s", request_id, traceback.format_exc())

        try:
            qr_fields = decode_qr(cccd_back_cropped)
            if qr_fields:
                logger.info("[%s] QR decoded: %d fields", request_id,
                            sum(1 for v in qr_fields.values() if v))
        except Exception:
            logger.error("[%s] QR decode failed:\n%s", request_id, traceback.format_exc())

    # --- Merge all front+back OCR/VLM fields ---
    combined_ocr = {**ocr_fields}
    for k, v in ocr_back_fields.items():
        if v and not combined_ocr.get(k):
            combined_ocr[k] = v

    combined_vlm = {**vlm_fields}
    for k, v in vlm_back_fields.items():
        if k in ("mrz_line_1", "mrz_line_2", "mrz_line_3"):
            continue
        if v and not combined_vlm.get(k):
            combined_vlm[k] = v

    # --- Cross-check with all available sources ---
    cross_result = cross_check(combined_ocr, combined_vlm, qr_fields, mrz_fields)
    source_count = 2 + (1 if qr_fields else 0) + (1 if mrz_fields else 0)
    logger.info("[%s] Cross-check (%d sources): agreement=%.2f",
                request_id, source_count, cross_result.agreement)

    # --- Face matching ---
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

    cross_details_data = [d.model_dump() for d in cross_result.details]

    record = VerificationRecord(
        id=request_id,
        status="success",
        identity=cross_result.merged,
        ocr_result=combined_ocr,
        vlm_result=combined_vlm,
        merged_result=cross_result.merged,
        ocr_vlm_agreement=cross_result.agreement,
        cross_check_details=cross_details_data,
        face_score=face_result.score,
        face_status=face_result.status,
        overall_confidence=overall,
        quality_issues=all_issues if all_issues else None,
        ocr_bboxes=ocr_bboxes_data,
        qr_result=qr_fields,
        mrz_result=mrz_fields,
        ocr_back_result=ocr_back_fields if ocr_back_fields else None,
        vlm_back_result=vlm_back_fields if vlm_back_fields else None,
        source_count=source_count,
        processing_time_ms=elapsed,
        cccd_path=str(cccd_path),
        cccd_back_path=cccd_back_path_str,
        selfie_path=str(selfie_path),
    )
    db.add(record)
    db.commit()

    sources_data: dict = {
        "ocr_front": ocr_fields,
        "vlm_front": vlm_fields,
    }
    if ocr_back_fields:
        sources_data["ocr_back"] = ocr_back_fields
    if vlm_back_fields:
        sources_data["vlm_back"] = vlm_back_fields
    if qr_fields:
        sources_data["qr"] = qr_fields
    if mrz_fields:
        sources_data["mrz"] = mrz_fields

    return VerifyResponse(
        request_id=request_id,
        status="success",
        identity=cross_result.merged,
        verification={
            "ocr_vlm_agreement": cross_result.agreement,
            "cross_check_details": cross_details_data,
            "face_match": {"score": face_result.score, "status": face_result.status},
            "overall_confidence": overall,
            "source_count": source_count,
        },
        sources=sources_data,
        processing_time_ms=round(elapsed, 1),
        ocr_bboxes=ocr_bboxes_data,
        quality_issues=all_issues if all_issues else None,
        image_paths={
            "cccd_front": str(cccd_path),
            "cccd_back": cccd_back_path_str,
            "selfie": str(selfie_path),
        },
    )


def _compute_overall(agreement: float, face_score: float, face_status: str) -> float:
    field_weight = 0.6
    face_weight = 0.4

    if face_status == "match":
        face_component = face_score
    elif face_status == "no_match":
        face_component = face_score * 0.3
    else:
        face_component = 0.0

    return round(min(agreement * field_weight + face_component * face_weight, 1.0), 4)


@router.get("/results")
async def list_results(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    total = db.query(func.count(VerificationRecord.id)).scalar() or 0
    records = (
        db.query(VerificationRecord)
        .order_by(VerificationRecord.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "items": [
            {
                "request_id": r.id,
                "status": r.status,
                "identity": r.merged_result,
                "overall_confidence": r.overall_confidence,
                "face_score": r.face_score,
                "face_status": r.face_status,
                "processing_time_ms": r.processing_time_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "quality_issues": r.quality_issues,
                "source_count": r.source_count,
                "has_back": r.cccd_back_path is not None,
            }
            for r in records
        ],
    }


@router.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    total = db.query(func.count(VerificationRecord.id)).scalar() or 0
    success = (
        db.query(func.count(VerificationRecord.id))
        .filter(VerificationRecord.status == "success")
        .scalar()
        or 0
    )
    avg_time = db.query(func.avg(VerificationRecord.processing_time_ms)).scalar() or 0
    return {
        "total": total,
        "success": success,
        "failed": total - success,
        "avg_processing_time_ms": round(float(avg_time), 1),
    }


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
            "cross_check_details": record.cross_check_details or [],
            "face_match": {"score": record.face_score, "status": record.face_status},
            "overall_confidence": record.overall_confidence,
            "source_count": record.source_count or 2,
        } if record.status == "success" else None,
        sources=_build_sources(record) if record.status == "success" else None,
        processing_time_ms=record.processing_time_ms or 0,
        ocr_bboxes=record.ocr_bboxes,
        quality_issues=record.quality_issues,
        image_paths={
            "cccd_front": record.cccd_path,
            "cccd_back": record.cccd_back_path,
            "selfie": record.selfie_path,
        } if record.cccd_path else None,
    )


@router.post("/liveness")
async def check_liveness(
    selfie_image: UploadFile = File(..., description="Selfie captured after liveness check"),
    liveness_passed: bool = Form(True),
):
    """Verify liveness from client-side results + server-side image analysis."""
    image_bytes = await selfie_image.read()
    try:
        img = read_image_from_bytes(image_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = verify_liveness(img, liveness_passed)
    return result


@router.post("/classify")
async def classify_image(
    image: UploadFile = File(..., description="Image to classify"),
):
    """Classify an image as cccd_front, cccd_back, or other."""
    image_bytes = await image.read()
    try:
        img = read_image_from_bytes(image_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = classify_document(img)
    return result


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "DocuMind eKYC API"}


def _build_sources(record: VerificationRecord) -> dict:
    sources: dict = {
        "ocr_front": record.ocr_result or {},
        "vlm_front": record.vlm_result or {},
    }
    if record.ocr_back_result:
        sources["ocr_back"] = record.ocr_back_result
    if record.vlm_back_result:
        sources["vlm_back"] = record.vlm_back_result
    if record.qr_result:
        sources["qr"] = record.qr_result
    if record.mrz_result:
        sources["mrz"] = record.mrz_result
    return sources
