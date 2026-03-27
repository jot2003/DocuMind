"""Quick test of the /api/verify endpoint."""
import json
import sys
import requests

sys.stdout.reconfigure(encoding="utf-8")


def main():
    cccd_path = "data/samples/cccd_001.png"
    selfie_path = "data/samples/cccd_002.png"

    print(f"Testing with CCCD: {cccd_path}, Selfie: {selfie_path}")
    print("Sending request to http://localhost:8000/api/verify ...")

    with open(cccd_path, "rb") as cccd, open(selfie_path, "rb") as selfie:
        r = requests.post(
            "http://localhost:8000/api/verify",
            files={
                "cccd_image": ("cccd.png", cccd, "image/png"),
                "selfie_image": ("selfie.png", selfie, "image/png"),
            },
            timeout=120,
        )

    print(f"HTTP Status: {r.status_code}")
    data = r.json()
    print(f"Request ID: {data.get('request_id')}")
    print(f"Result Status: {data.get('status')}")
    print()

    if data.get("identity"):
        print("=== Identity (Merged) ===")
        for k, v in data["identity"].items():
            print(f"  {k}: {v}")
        print()

    if data.get("verification"):
        v = data["verification"]
        print("=== Verification Scores ===")
        agreement = v.get("ocr_vlm_agreement", 0)
        print(f"  OCR-VLM Agreement: {agreement*100:.0f}%")

        fm = v.get("face_match", {})
        print(f"  Face: {fm.get('status')} ({fm.get('score', 0)*100:.0f}%)")
        print(f"  Overall Confidence: {v.get('overall_confidence', 0)*100:.0f}%")
        print()

        details = v.get("cross_check_details", [])
        if details:
            print("=== Cross-Check Details ===")
            for d in details:
                sim = d.get("similarity", 0) * 100
                print(f"  {d['field']:20s} OCR={str(d.get('ocr_value',''))[:25]:25s} "
                      f"VLM={str(d.get('vlm_value',''))[:25]:25s} "
                      f"sim={sim:.0f}% src={d.get('chosen_source')}")
        print()

    if data.get("quality_issues"):
        print("=== Quality Issues ===")
        for issue in data["quality_issues"]:
            print(f"  - {issue}")

    print(f"\nProcessing time: {data.get('processing_time_ms', 0)/1000:.1f}s")
    print("\nFull JSON saved to: test_result.json")
    with open("test_result.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
