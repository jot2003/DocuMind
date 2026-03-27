import re
import logging

logger = logging.getLogger(__name__)


def parse_mrz(ocr_text: str) -> dict[str, str | None] | None:
    """
    Parse MRZ (Machine Readable Zone) from CCCD back side OCR text.
    Vietnamese CCCD uses TD1 format (3 lines, 30 chars each).

    Line 1: IDVNM + document number + check digit + optional data
    Line 2: DOB + check digit + sex + expiry + check digit + nationality + optional + check
    Line 3: Name (SURNAME<<GIVEN_NAMES)
    """
    lines = _extract_mrz_lines(ocr_text)
    if not lines:
        logger.warning("No MRZ lines found in OCR text")
        return None

    logger.info("Found %d MRZ lines", len(lines))

    fields: dict[str, str | None] = {
        "so_cccd": None,
        "ngay_sinh": None,
        "gioi_tinh": None,
        "ngay_het_han": None,
        "ho_ten": None,
    }

    if len(lines) >= 1:
        line1 = lines[0]
        doc_number = _extract_document_number(line1)
        if doc_number:
            fields["so_cccd"] = doc_number

    if len(lines) >= 2:
        line2 = lines[1]
        dob = _extract_date(line2, 0, 6)
        if dob:
            fields["ngay_sinh"] = dob

        sex = _extract_sex(line2)
        if sex:
            fields["gioi_tinh"] = sex

        expiry = _extract_date(line2, 8, 14)
        if expiry:
            fields["ngay_het_han"] = expiry

    if len(lines) >= 3:
        name = _extract_name(lines[2])
        if name:
            fields["ho_ten"] = name

    found_count = sum(1 for v in fields.values() if v)
    logger.info("MRZ parsed: %d/5 fields found", found_count)
    return fields if found_count > 0 else None


def _extract_mrz_lines(text: str) -> list[str]:
    """Extract lines that look like MRZ data (mostly uppercase letters, digits, and < characters)."""
    mrz_pattern = re.compile(r"[A-Z0-9<]{20,}")
    candidates = []

    for line in text.split("\n"):
        cleaned = line.strip().upper().replace(" ", "")
        cleaned = cleaned.replace("Đ", "D").replace("đ", "d")
        cleaned = re.sub(r"[^A-Z0-9<]", "", cleaned)

        if len(cleaned) >= 25:
            matches = mrz_pattern.findall(cleaned)
            for m in matches:
                if len(m) >= 25 and m.count("<") >= 1:
                    padded = m.ljust(30, "<")[:30]
                    candidates.append(padded)

    if not candidates:
        return []

    ordered = []
    for c in candidates:
        normalized = _normalize_line1_prefix(c)
        if normalized.startswith("IDVNM"):
            ordered.insert(0, normalized)
        elif "<<" in c and re.search(r"[A-Z]{3,}", c):
            ordered.append(c)
        else:
            ordered.insert(len(ordered) // 2 if ordered else 0, c)

    return ordered[:3]


def _normalize_line1_prefix(line: str) -> str:
    """Fix common OCR misreads of the 'IDVNM' prefix."""
    if line.startswith("IDVNM") or line.startswith("1DVNM"):
        return line
    if line.startswith("VNM") and len(line) >= 28:
        return "ID" + line
    if len(line) >= 2 and line[1:].startswith("DVNM"):
        return "I" + line[1:]
    if len(line) >= 2 and line[0:2] != "ID" and line[2:].startswith("VNM"):
        return "ID" + line[2:]
    return line


def _extract_document_number(line1: str) -> str | None:
    """Extract 12-digit CCCD number from MRZ line 1.

    TD1 Line 1 layout (30 chars):
      [0:2]  Type (ID)
      [2:5]  Country (VNM)
      [5:14] Document number (9 digits)
      [14]   Check digit
      [15:27] Optional data → 12-digit CCCD number
      [27:30] Filler / check
    """
    if line1.startswith("IDVNM") or line1.startswith("1DVNM"):
        if len(line1) >= 27:
            optional = line1[15:27].replace("<", "")
            cccd_digits = re.sub(r"\D", "", optional)
            if len(cccd_digits) == 12:
                return cccd_digits
            if len(cccd_digits) >= 9:
                return cccd_digits.zfill(12)

        doc_num = line1[5:14].replace("<", "")
        doc_digits = re.sub(r"\D", "", doc_num)
        if len(doc_digits) >= 9:
            return doc_digits.zfill(12)

    all_digits = re.findall(r"0\d{11}", line1)
    if all_digits:
        return all_digits[0]

    any_12 = re.findall(r"\d{12}", line1)
    if any_12:
        return any_12[-1]

    return None


def _extract_date(line: str, start: int, end: int) -> str | None:
    """Extract date in YYMMDD format from MRZ line and convert to DD/MM/YYYY."""
    if len(line) <= end:
        return None

    raw = line[start:end]
    if not raw.isdigit() or len(raw) != 6:
        return None

    yy, mm, dd = raw[:2], raw[2:4], raw[4:6]
    year = int(yy)
    century = "19" if year > 50 else "20"
    return f"{dd}/{mm}/{century}{yy}"


def _extract_sex(line: str) -> str | None:
    """Extract sex from MRZ line 2 (position 7)."""
    if len(line) < 8:
        return None
    sex_char = line[7]
    if sex_char == "M":
        return "Nam"
    elif sex_char == "F":
        return "Nữ"
    return None


def _extract_name(line3: str) -> str | None:
    """Extract name from MRZ line 3 (format: SURNAME<<GIVEN_NAMES<<<...)."""
    cleaned = line3.strip().rstrip("<")
    if "<<" not in cleaned:
        return None

    parts = cleaned.split("<<", 1)
    surname = parts[0].replace("<", " ").strip()
    given = parts[1].replace("<", " ").strip() if len(parts) > 1 else ""

    if surname or given:
        full_name = f"{surname} {given}".strip()
        return full_name.upper() if full_name else None
    return None
