import re
import logging

from backend.models.schemas import OCRLine

logger = logging.getLogger(__name__)

LABEL_ALIASES = {
    "ho_ten": [
        "Họ và tên", "Ho va ten", "Full name", "Họ và tên/Full name",
        "họ và tên", "Ho và tên",
    ],
    "ngay_sinh": [
        "Ngày sinh", "Date of birth", "Ngay sinh", "ngày sinh",
        "Ngày, tháng, năm sinh",
    ],
    "gioi_tinh": [
        "Giới tính", "Sex", "Gioi tinh", "giới tính",
    ],
    "quoc_tich": [
        "Quốc tịch", "Nationality", "Quoc tich", "quốc tịch",
    ],
    "que_quan": [
        "Quê quán", "Place of origin", "Que quan", "quê quán",
    ],
    "noi_thuong_tru": [
        "Nơi thường trú", "Place of residence", "Noi thuong tru",
        "nơi thường trú",
    ],
    "ngay_het_han": [
        "Có giá trị đến", "Date of expiry", "Co gia tri den",
        "có giá trị đến", "Ngày hết hạn", "ngày hết hạn",
    ],
}

BACK_LABEL_ALIASES = {
    "noi_thuong_tru": [
        "Nơi cư trú", "Place of residence", "Noi cu tru", "nơi cư trú",
        "Nơi thường trú", "nơi thường trú",
    ],
    "que_quan": [
        "Nơi đăng ký khai sinh", "Place of birth registration",
        "nơi đăng ký khai sinh", "Noi dang ky khai sinh",
        "Quê quán", "quê quán",
    ],
    "ngay_cap": [
        "Ngày, tháng, năm cấp", "Ngày cấp", "Date of issue",
        "ngày cấp", "Ngay cap", "Date, month, year",
        "Ngày, tháng, năm",
    ],
    "ngay_het_han": [
        "Có giá trị đến", "Date of expiry", "có giá trị đến",
        "Ngày hết hạn", "ngày hết hạn",
        "Ngày, tháng, năm hết hạn",
    ],
    "noi_cap": [
        "Nơi cấp", "Place of issue", "nơi cấp", "Noi cap",
    ],
    "dac_diem_nhan_dang": [
        "Đặc điểm nhận dạng", "Dac diem nhan dang",
        "Personal identification", "đặc điểm nhận dạng",
    ],
}

CCCD_NUMBER_PATTERN = re.compile(r"(?<!\d)\d{12}(?!\d)")
DATE_PATTERN = re.compile(r"\b\d{2}[/\-\.]\d{2}[/\-\.]\d{4}\b")
GENDER_PATTERN = re.compile(r"\b(Nam|Nữ|Male|Female)\b", re.IGNORECASE)
NATIONALITY_PATTERN = re.compile(
    r"(Việt Nam|VIỆT NAM|Viet Nam|VIET NAM|Vietnamese)", re.IGNORECASE
)


def extract_cccd_fields(ocr_text: str, ocr_lines: list[OCRLine]) -> dict[str, str | None]:
    fields: dict[str, str | None] = {
        "so_cccd": None,
        "ho_ten": None,
        "ngay_sinh": None,
        "gioi_tinh": None,
        "quoc_tich": None,
        "que_quan": None,
        "noi_thuong_tru": None,
        "ngay_het_han": None,
    }

    cccd_match = CCCD_NUMBER_PATTERN.search(ocr_text)
    if cccd_match:
        fields["so_cccd"] = cccd_match.group()

    gender_match = GENDER_PATTERN.search(ocr_text)
    if gender_match:
        val = gender_match.group()
        fields["gioi_tinh"] = "Nam" if val.lower() in ("nam", "male") else "Nữ"

    nat_match = NATIONALITY_PATTERN.search(ocr_text)
    if nat_match:
        fields["quoc_tich"] = "Việt Nam"

    dates = DATE_PATTERN.findall(ocr_text)
    if dates:
        fields["ngay_sinh"] = dates[0]
        if len(dates) >= 2:
            fields["ngay_het_han"] = dates[-1]

    line_texts = [l.text.strip() for l in ocr_lines]

    for field_key, aliases in LABEL_ALIASES.items():
        if fields[field_key] is not None:
            continue
        value = _find_value_after_label(line_texts, aliases)
        if value:
            fields[field_key] = value

    if not fields["ho_ten"]:
        fields["ho_ten"] = _find_name_heuristic(line_texts)

    logger.info("Extracted CCCD fields: %s", {k: v for k, v in fields.items() if v})
    return fields


def extract_cccd_back_fields(
    ocr_text: str, ocr_lines: list[OCRLine]
) -> dict[str, str | None]:
    fields: dict[str, str | None] = {
        "noi_thuong_tru": None,
        "que_quan": None,
        "ngay_cap": None,
        "ngay_het_han": None,
        "noi_cap": None,
        "dac_diem_nhan_dang": None,
    }

    dates = DATE_PATTERN.findall(ocr_text)
    if dates:
        fields["ngay_cap"] = dates[0]
        if len(dates) >= 2:
            fields["ngay_het_han"] = dates[-1]

    line_texts = [l.text.strip() for l in ocr_lines]

    for field_key, aliases in BACK_LABEL_ALIASES.items():
        if fields[field_key] is not None:
            continue
        value = _find_value_after_label(line_texts, aliases)
        if value:
            fields[field_key] = value

    result = {k: v for k, v in fields.items() if v is not None}
    logger.info("Extracted CCCD back fields: %s", result)
    return fields


def _find_value_after_label(
    line_texts: list[str], label_aliases: list[str]
) -> str | None:
    all_labels = list(LABEL_ALIASES.values()) + list(BACK_LABEL_ALIASES.values())

    for i, line in enumerate(line_texts):
        for alias in label_aliases:
            if alias.lower() in line.lower():
                after_colon = line.split(":", 1)
                if len(after_colon) > 1 and after_colon[1].strip():
                    return after_colon[1].strip()

                after_slash = line.split("/", 1)
                if len(after_slash) > 1 and len(after_slash[1].strip()) > 3:
                    remaining = after_slash[1].strip()
                    parts = remaining.split(":", 1)
                    if len(parts) > 1:
                        return parts[1].strip()

                if i + 1 < len(line_texts):
                    next_line = line_texts[i + 1]
                    is_label = any(
                        a.lower() in next_line.lower()
                        for aliases_list in all_labels
                        for a in aliases_list
                    )
                    if not is_label and len(next_line) > 1:
                        return next_line
    return None


_VIET_NAME_RE = re.compile(
    r"[A-ZÀ-ỹĐ][A-ZÀ-ỹĐa-zà-ỹđ]*"
    r"(?:\s+[A-ZÀ-ỹĐ][A-ZÀ-ỹĐa-zà-ỹđ]*){1,5}"
)

_NAME_SKIP = {
    "cộng", "hòa", "xã", "hội", "chủ", "nghĩa", "căn", "cước", "công", "dân",
    "citizen", "socialist", "republic", "independent", "freedom", "happiness",
    "việt", "nam", "viet", "identity", "card", "quốc", "tịch", "nationality",
    "doc", "lap", "tu", "do", "hanh", "phuc", "giới", "tính", "ngày", "sinh",
    "full", "name", "date", "birth", "sex", "number", "place", "residence",
    "origin", "expiry", "cong", "dan",
}


def _find_name_heuristic(line_texts: list[str]) -> str | None:
    cccd_line_idx = -1
    for i, line in enumerate(line_texts):
        if re.search(r"\d{12}", line):
            cccd_line_idx = i
            break

    candidates = []
    for i, line in enumerate(line_texts):
        if cccd_line_idx >= 0 and i < cccd_line_idx:
            continue

        for m in _VIET_NAME_RE.finditer(line):
            name_candidate = m.group().strip()
            words = name_candidate.split()
            if len(words) < 2 or len(words) > 6:
                continue
            if len(name_candidate) < 6:
                continue
            lower_words = {w.lower() for w in words}
            if lower_words & _NAME_SKIP:
                continue
            candidates.append(name_candidate.upper())

    if not candidates:
        return None
    return max(candidates, key=len)
