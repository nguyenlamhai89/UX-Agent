from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import translate_to_vie as skill  # noqa: E402


ORIGINAL_MARKDOWN = """# Reliable AI Evaluation

## Abstract

We studied 42 participants [1] using the AI system.

## Method

The method preserves DOI 10.1234/example, `model_id`, and unit 5 kg.

| Measure | Value |
| --- | --- |
| Sample | 42 |

![Figure 1](Asset/page-001-figure-001.png)

## References

[1] Example reference. https://example.org/paper
"""


def create_converter_output(root: Path, *, language: str = "en", title: str = "Reliable AI Evaluation"):
    requested = str(root / "input-paper.pdf")
    renamed_pdf = root / f"{title}.pdf"
    renamed_pdf.write_bytes(
        (f"%PDF-1.4\nTITLE:{title}\nLANG:{language}\n%%EOF\n").encode("utf-8")
    )
    paper_folder = root / title
    paper_folder.mkdir()
    original_md = paper_folder / "original.md"
    original_md.write_text(ORIGINAL_MARKDOWN, encoding="utf-8")
    asset_dir = paper_folder / "Asset"
    asset_dir.mkdir()
    asset = asset_dir / "page-001-figure-001.png"
    asset.write_bytes(b"fake-image")
    manifest_path = paper_folder / ".conversion-manifest.json"
    manifest = {
        "schema_version": skill.MANIFEST_SCHEMA_VERSION,
        "skill_version": "2.0.0-test",
        "status": "success",
        "conversion_status": "SUCCESS",
        "url_path": requested,
        "source_identity": {
            "source_type": "local_pdf",
            "requested_url": requested,
            "resolved_url": requested,
            "original_name": "input-paper.pdf",
        },
        "renamed_pdf": str(renamed_pdf),
        "paper_folder": str(paper_folder),
        "original_md": str(original_md),
        "asset_dir": str(asset_dir),
        "manifest": str(manifest_path),
        "source_sha256": skill.sha256_file(renamed_pdf),
        "original_md_sha256": skill.sha256_file(original_md),
        "source_language": {"language": language, "confidence": 0.99},
        "docling_version": "2.117.0-test",
        "asset_inventory": [{"path": "Asset/page-001-figure-001.png"}],
        "artifact_hashes": {
            "original.md": skill.sha256_file(original_md),
            "Asset/page-001-figure-001.png": skill.sha256_file(asset),
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    handoff = {
        "status": "success",
        "url_path": requested,
        "pdf_count": 1,
        "results": [
            {
                "status": "success",
                "renamed_pdf": str(renamed_pdf),
                "output_dir": str(paper_folder),
                "original_md": str(original_md),
                "asset_dir": str(asset_dir),
                "manifest": str(manifest_path),
                "source_language": {"language": language, "confidence": 0.99},
            }
        ],
    }
    return {
        "url_path": requested,
        "handoff": handoff,
        "manifest": manifest_path,
        "renamed_pdf": renamed_pdf,
        "paper_folder": paper_folder,
        "original_md": original_md,
        "asset_dir": asset_dir,
    }


def voice_response(resolved, blocks):
    return {
        "schema_version": skill.VOICE_SCHEMA_VERSION,
        "language": "vi",
        "source_sha256": resolved["source_sha256"],
        "original_md_sha256": resolved["original_md_sha256"],
        "source_block_ids": [block.block_id for block in blocks],
        "profile": {
            "ngoi_ke": "Giọng văn học thuật ở ngôi thứ nhất số nhiều khi mô tả nghiên cứu.",
            "muc_do_trang_trong": "Trang trọng, chính xác và nhất quán.",
            "lap_truong_hoc_thuat": "Khách quan, dựa trên bằng chứng.",
            "muc_do_chac_chan": "Thận trọng khi suy luận và rõ ràng khi báo cáo dữ liệu.",
            "nhip_va_cau_truc_cau": "Câu có nhịp vừa phải, ưu tiên cấu trúc logic.",
            "mat_do_dien_dat": "Mật độ thông tin cao nhưng dễ theo dõi.",
            "van_phong_chuyen_nganh": "Dùng thuật ngữ nghiên cứu và AI nhất quán.",
            "lap_luan_va_bang_chung": "Trình bày lập luận theo dữ liệu và trích dẫn nguồn.",
        },
        "translation_rules": [
            "Dịch đầy đủ từng câu và giữ nguyên độ chắc chắn của tác giả.",
            "Giữ cấu trúc Markdown và mọi nội dung kỹ thuật được bảo vệ.",
        ],
        "preferred_terms": [
            {"source_term": "participants", "vietnamese": "người tham gia", "note": "Dùng nhất quán."}
        ],
        "protected_content_rules": [
            "Không được thay đổi URL, DOI, trích dẫn, công thức, số, đơn vị hoặc mã.",
            "Không được thay đổi cấu trúc Markdown, liên kết hoặc nội dung code.",
        ],
    }


TRANSLATIONS = {
    "# Reliable AI Evaluation": "# Đánh giá AI đáng tin cậy",
    "## Abstract": "## Tóm tắt",
    "We studied 42 participants [1] using the AI system.": "Chúng tôi nghiên cứu 42 người tham gia [1] bằng hệ thống AI.",
    "## Method": "## Phương pháp",
    "The method preserves DOI 10.1234/example, `model_id`, and unit 5 kg.": "Phương pháp giữ nguyên DOI 10.1234/example, `model_id` và đơn vị 5 kg.",
    "| Measure | Value |": "| Chỉ số | Giá trị |",
    "| Sample | 42 |": "| Mẫu | 42 |",
    "![Figure 1](Asset/page-001-figure-001.png)": "![Hình 1](Asset/page-001-figure-001.png)",
    "## References": "## Tài liệu tham khảo",
}


def translation_response(resolved, blocks):
    return {
        "schema_version": skill.TRANSLATION_SCHEMA_VERSION,
        "source_sha256": resolved["source_sha256"],
        "original_md_sha256": resolved["original_md_sha256"],
        "blocks": [
            {
                "block_id": block.block_id,
                "kind": block.kind,
                "translated_text": TRANSLATIONS.get(block.raw, block.raw),
            }
            for block in blocks
            if block.translatable
        ],
    }


def audit_response(resolved):
    return {
        "schema_version": skill.AUDIT_SCHEMA_VERSION,
        "source_sha256": resolved["source_sha256"],
        "original_md_sha256": resolved["original_md_sha256"],
        "passed": True,
        "issues": [],
    }


@pytest.fixture
def converted_paper(tmp_path):
    return create_converter_output(tmp_path)
