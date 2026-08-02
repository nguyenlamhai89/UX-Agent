from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import convert_researchpaper_to_md as skill  # noqa: E402


def write_test_pdf(path: Path, title: str, language: str = "en", partial: bool = False) -> Path:
    """Create a compact PDF-signature fixture understood by FakeDoclingEngine."""
    partial_value = "yes" if partial else "no"
    payload = (
        f"%PDF-1.4\n"
        f"TITLE:{title}\n"
        f"LANG:{language}\n"
        f"PARTIAL:{partial_value}\n"
        f"1 0 obj << /Type /Catalog >> endobj\n"
        f"%%EOF\n"
    )
    path.write_bytes(payload.encode("utf-8"))
    return path


class FakeDoclingEngine:
    docling_version = "2.117.0-fake"

    @staticmethod
    def _metadata(path: Path):
        text = path.read_text(encoding="utf-8", errors="replace")
        values = {}
        for line in text.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                values[key] = value
        return values

    def preflight(self, source: Path, job_dir: Path):
        metadata = self._metadata(source)
        title = metadata.get("TITLE", "Untitled")
        candidates = [
            {
                "order": 0,
                "label": "page_header",
                "content_layer": "furniture",
                "text": "Journal masthead",
                "page_no": 1,
            },
            {
                "order": 1,
                "label": "title",
                "content_layer": "body",
                "text": title,
                "page_no": 1,
                "self_ref": "#/texts/0",
            },
        ]
        selected = skill.select_title_candidate(candidates)
        job_dir.mkdir(parents=True, exist_ok=True)
        first_page = job_dir / "first-page.png"
        first_page.write_bytes(b"fake-png")
        return skill.PreflightBundle(candidates, selected, str(first_page), self.docling_version, "SUCCESS")

    def convert(self, source: Path, staging_dir: Path):
        metadata = self._metadata(source)
        if metadata.get("PARTIAL") == "yes":
            raise skill.SkillError(
                "DOCLING_PARTIAL_SUCCESS",
                "Fake partial conversion requires review.",
                status="PARTIAL_SUCCESS",
            )
        title = metadata.get("TITLE", source.stem)
        language = metadata.get("LANG", "en")
        assert source.exists(), "source must already be renamed before full conversion"
        assert source.with_suffix("").is_dir(), "output folder must exist before conversion"
        staging_dir.mkdir(parents=True, exist_ok=True)
        asset_dir = staging_dir / "Asset"
        asset_dir.mkdir(parents=True, exist_ok=True)
        asset = asset_dir / "page-001-figure-001.png"
        asset.write_bytes(b"fake-figure")
        if language == "vi":
            abstract = "Đây là nội dung đầy đủ gồm 42 người tham gia [1]."
            method = "Phương pháp giữ nguyên DOI 10.1234/example và đơn vị 5 kg."
        else:
            abstract = "Complete source content with 42 participants [1]."
            method = "The method preserves DOI 10.1234/example and unit 5 kg."
        markdown = f"""# {title}

## Abstract

{abstract}

## Method

{method}

| Measure | Value |
| --- | --- |
| Sample | 42 |

![Figure 1](Asset/page-001-figure-001.png)

## References

[1] Example reference. https://example.org/paper
"""
        skill.atomic_write_text(staging_dir / "original.md", markdown)
        inventory = {
            "page_count": 1,
            "items": [
                {"order": 0, "level": 1, "label": "title", "text": title, "page_no": 1},
                {"order": 1, "level": 2, "label": "section_header", "text": "Abstract", "page_no": 1},
            ],
            "asset_count": 1,
        }
        skill.atomic_write_json(staging_dir / "lossless-docling.json", {"docling": {}, "normalized": inventory})
        assets = [
            {
                "path": "Asset/page-001-figure-001.png",
                "kind": "picture",
                "page_no": 1,
                "sha256": skill.sha256_file(asset),
            }
        ]
        return skill.ConversionBundle("SUCCESS", self.docling_version, 1, assets, inventory, [])


class FakeAIRunner:
    def __init__(self, title_confidence: float = 0.99, malformed_translation: bool = False):
        self.title_confidence = title_confidence
        self.malformed_translation = malformed_translation

    def validate_title(self, preflight):
        return {
            "valid": self.title_confidence >= skill.MIN_TITLE_CONFIDENCE,
            "confidence": self.title_confidence,
            "title": preflight["selected_candidate"]["text"],
            "reason": "Matches the first-page title.",
        }

    def detect_language(self, state):
        source = Path(state["renamed_pdf"]).read_text(encoding="utf-8", errors="replace")
        language = "vi" if "LANG:vi" in source else "en"
        return {"language": language, "confidence": 0.99, "reason": "Fixture language marker."}

    def translate(self, state):
        original = Path(state["original_draft"]).read_text(encoding="utf-8")
        translated = (
            original.replace("## Abstract", "## Tóm tắt")
            .replace("Complete source content with", "Nội dung nguồn đầy đủ với")
            .replace("participants", "người tham gia")
            .replace("## Method", "## Phương pháp")
            .replace("The method preserves", "Phương pháp giữ nguyên")
            .replace("and unit", "và đơn vị")
            .replace("| Measure | Value |", "| Chỉ số | Giá trị |")
            .replace("| Sample |", "| Mẫu |")
            .replace("![Figure 1]", "![Hình 1]")
            .replace("## References", "## Tài liệu tham khảo")
        )
        if self.malformed_translation:
            translated = translated.replace("## Phương pháp", "### Phương pháp").replace("42", "41", 1)
        target = Path(state["staging_dir"]) / "ai-vie.md"
        target.write_text(translated, encoding="utf-8")
        return target

    def audit(self, state, language_decision, translation_path):
        return {"passed": True, "issues": []}


class FakeHttpClient:
    def __init__(self, responses):
        self.responses = responses

    def fetch(self, url, max_bytes):
        final_url, content_type, data = self.responses[url]
        assert len(data) <= max_bytes
        return final_url, content_type, data


@pytest.fixture
def fake_docling():
    return FakeDoclingEngine()


@pytest.fixture
def fake_ai():
    return FakeAIRunner()


@pytest.fixture
def pdf_factory():
    return write_test_pdf
