import logging
from Levenshtein import ratio as levenshtein_ratio

from backend.models.schemas import FieldComparison, CrossCheckResult

logger = logging.getLogger(__name__)

FIELD_TRUST: dict[str, str] = {
    "so_cccd":         "ocr",
    "ho_ten":          "vlm",
    "ngay_sinh":       "ocr",
    "gioi_tinh":       "vlm",
    "quoc_tich":       "vlm",
    "que_quan":        "vlm",
    "noi_thuong_tru":  "vlm",
    "ngay_het_han":    "ocr",
    "ngay_cap":        "vlm",
    "dac_diem_nhan_dang": "vlm",
}

SIMILARITY_THRESHOLD = 0.85


def cross_check(
    ocr_fields: dict[str, str | None],
    vlm_fields: dict[str, str | None],
    qr_fields: dict[str, str | None] | None = None,
    mrz_fields: dict[str, str | None] | None = None,
) -> CrossCheckResult:
    """
    Cross-check extracted fields from multiple sources.
    When QR/MRZ data is available, uses majority voting for higher confidence.
    """
    all_keys = sorted(set(
        list(ocr_fields.keys()) +
        list(vlm_fields.keys()) +
        list((qr_fields or {}).keys()) +
        list((mrz_fields or {}).keys())
    ))

    details: list[FieldComparison] = []
    merged: dict[str, str | None] = {}
    agree_count = 0

    for key in all_keys:
        ocr_val = ocr_fields.get(key)
        vlm_val = vlm_fields.get(key)
        qr_val = (qr_fields or {}).get(key)
        mrz_val = (mrz_fields or {}).get(key)

        sources = {
            "ocr": ocr_val,
            "vlm": vlm_val,
        }
        if qr_val:
            sources["qr"] = qr_val
        if mrz_val:
            sources["mrz"] = mrz_val

        sim = _compute_similarity(ocr_val, vlm_val)

        if qr_val or mrz_val:
            extra_sims = []
            for extra_val in [qr_val, mrz_val]:
                if extra_val:
                    if ocr_val:
                        extra_sims.append(_compute_similarity(ocr_val, extra_val))
                    if vlm_val:
                        extra_sims.append(_compute_similarity(vlm_val, extra_val))
            if extra_sims:
                sim = max(sim, max(extra_sims))

        if sim >= SIMILARITY_THRESHOLD:
            agree_count += 1

        chosen_source, chosen_val = _pick_best_multi(key, sources, sim)
        merged[key] = chosen_val

        details.append(FieldComparison(
            field=key,
            ocr_value=ocr_val,
            vlm_value=vlm_val,
            similarity=round(sim, 4),
            chosen_source=chosen_source,
        ))

    fields_with_any = sum(
        1 for k in all_keys
        if ocr_fields.get(k) or vlm_fields.get(k) or
        (qr_fields or {}).get(k) or (mrz_fields or {}).get(k)
    )
    agreement = min(agree_count / fields_with_any, 1.0) if fields_with_any else 0.0

    source_count = 2 + (1 if qr_fields else 0) + (1 if mrz_fields else 0)
    logger.info(
        "Cross-check (%d sources): %d/%d agree (%.0f%%), merged %d fields",
        source_count, agree_count, fields_with_any, agreement * 100, len(merged),
    )

    return CrossCheckResult(
        merged=merged,
        details=details,
        agreement=round(agreement, 4),
    )


def _compute_similarity(a: str | None, b: str | None) -> float:
    if a is None or b is None:
        return 0.0
    return levenshtein_ratio(a.strip().lower(), b.strip().lower())


def _pick_best_multi(
    field: str,
    sources: dict[str, str | None],
    sim: float,
) -> tuple[str, str | None]:
    non_null = {k: v for k, v in sources.items() if v}

    if not non_null:
        return "none", None
    if len(non_null) == 1:
        src = next(iter(non_null))
        return src, non_null[src]

    if "qr" in non_null:
        if field in ("so_cccd", "ngay_sinh", "gioi_tinh"):
            return "qr", non_null["qr"]

    if "mrz" in non_null:
        if field in ("so_cccd", "ngay_sinh", "gioi_tinh", "ngay_het_han"):
            return "mrz", non_null["mrz"]

    preferred = FIELD_TRUST.get(field, "vlm")
    if preferred in non_null:
        return preferred, non_null[preferred]

    src = next(iter(non_null))
    return src, non_null[src]
