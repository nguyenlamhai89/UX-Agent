from __future__ import annotations

import json

import convert_researchpaper_to_md as skill
from conftest import FakeAIRunner


def test_e2e_batch_english_and_vietnamese_outputs(tmp_path, pdf_factory, fake_docling):
    pdf_factory(tmp_path / "unknown-a.pdf", "Human-Centered Evaluation of AI Systems", language="en")
    pdf_factory(tmp_path / "unknown-b.pdf", "Đánh giá trải nghiệm người dùng", language="vi")

    result = skill.convert_research_papers(
        str(tmp_path),
        ai_runner=FakeAIRunner(),
        docling_engine=fake_docling,
        workspace_root=tmp_path,
    )

    assert result["status"] == "success"
    assert result["pdf_count"] == 2
    assert result["succeeded"] == 2

    english_pdf = tmp_path / "Human-Centered Evaluation of AI Systems.pdf"
    english_dir = tmp_path / "Human-Centered Evaluation of AI Systems"
    assert english_pdf.is_file()
    assert (english_dir / "original.md").is_file()
    assert (english_dir / "vie.md").is_file()
    assert (english_dir / "Asset" / "page-001-figure-001.png").is_file()
    english_manifest = json.loads((english_dir / ".conversion-manifest.json").read_text(encoding="utf-8"))
    assert english_manifest["vietnamese_created"] is True
    skill.validate_markdown_parity(
        (english_dir / "original.md").read_text(encoding="utf-8"),
        (english_dir / "vie.md").read_text(encoding="utf-8"),
    )

    vietnamese_pdf = tmp_path / "Đánh giá trải nghiệm người dùng.pdf"
    vietnamese_dir = tmp_path / "Đánh giá trải nghiệm người dùng"
    assert vietnamese_pdf.is_file()
    assert (vietnamese_dir / "original.md").is_file()
    assert not (vietnamese_dir / "vie.md").exists()
    assert (vietnamese_dir / "Asset" / "page-001-figure-001.png").is_file()
    vietnamese_manifest = json.loads((vietnamese_dir / ".conversion-manifest.json").read_text(encoding="utf-8"))
    assert vietnamese_manifest["vietnamese_created"] is False


def test_e2e_translation_structure_failure_publishes_nothing(tmp_path, pdf_factory, fake_docling):
    pdf_factory(tmp_path / "unsafe.pdf", "Parity Gate Research", language="en")
    result = skill.convert_research_papers(
        str(tmp_path / "unsafe.pdf"),
        ai_runner=FakeAIRunner(malformed_translation=True),
        docling_engine=fake_docling,
        workspace_root=tmp_path,
    )
    assert result["status"] == "error"
    output = tmp_path / "Parity Gate Research"
    assert (tmp_path / "Parity Gate Research.pdf").is_file()
    assert not (output / "original.md").exists()
    assert not (output / "vie.md").exists()
    assert not (output / ".conversion-manifest.json").exists()
