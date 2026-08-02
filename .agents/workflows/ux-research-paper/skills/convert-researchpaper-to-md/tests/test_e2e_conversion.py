from __future__ import annotations

import json

import convert_researchpaper_to_md as skill
from conftest import FakeAIRunner


def test_e2e_batch_publishes_source_only_outputs(tmp_path, pdf_factory, fake_docling):
    english_source = pdf_factory(tmp_path / "unknown-a.pdf", "Human-Centered Evaluation of AI Systems", language="en")

    english_result = skill.convert_research_papers(
        str(english_source),
        ai_runner=FakeAIRunner(),
        docling_engine=fake_docling,
        workspace_root=tmp_path,
    )

    assert english_result["status"] == "success"
    assert english_result["pdf_count"] == 1
    assert english_result["succeeded"] == 1

    english_pdf = tmp_path / "Human-Centered Evaluation of AI Systems.pdf"
    english_dir = tmp_path / "Human-Centered Evaluation of AI Systems"
    assert english_pdf.is_file()
    assert (english_dir / "original.md").is_file()
    assert not (english_dir / "vie.md").exists()
    assert (english_dir / "Asset" / "page-001-figure-001.png").is_file()
    english_manifest = json.loads((english_dir / ".conversion-manifest.json").read_text(encoding="utf-8"))
    assert english_manifest["schema_version"] == "converter-manifest-v2"
    assert english_manifest["source_language"]["language"] == "en"
    assert english_manifest["original_md_sha256"] == skill.sha256_file(english_dir / "original.md")

    vietnamese_source = pdf_factory(tmp_path / "unknown-b.pdf", "Đánh giá trải nghiệm người dùng", language="vi")
    vietnamese_result = skill.convert_research_papers(
        str(vietnamese_source),
        ai_runner=FakeAIRunner(),
        docling_engine=fake_docling,
        workspace_root=tmp_path,
    )
    assert vietnamese_result["status"] == "success"

    vietnamese_pdf = tmp_path / "Đánh giá trải nghiệm người dùng.pdf"
    vietnamese_dir = tmp_path / "Đánh giá trải nghiệm người dùng"
    assert vietnamese_pdf.is_file()
    assert (vietnamese_dir / "original.md").is_file()
    assert not (vietnamese_dir / "vie.md").exists()
    assert (vietnamese_dir / "Asset" / "page-001-figure-001.png").is_file()
    vietnamese_manifest = json.loads((vietnamese_dir / ".conversion-manifest.json").read_text(encoding="utf-8"))
    assert vietnamese_manifest["schema_version"] == "converter-manifest-v2"
    assert vietnamese_manifest["source_language"]["language"] == "vi"


def test_e2e_multiple_papers_require_exact_selection(tmp_path, pdf_factory, fake_docling):
    pdf_factory(tmp_path / "a.pdf", "Paper A")
    pdf_factory(tmp_path / "b.pdf", "Paper B")
    result = skill.convert_research_papers(
        str(tmp_path),
        ai_runner=FakeAIRunner(),
        docling_engine=fake_docling,
        workspace_root=tmp_path,
    )
    assert result["status"] == "error"
    assert result["error_code"] == "MULTIPLE_PDFS_DISCOVERED"
    assert result["pdf_count"] == 2
    assert (tmp_path / "a.pdf").is_file()
    assert (tmp_path / "b.pdf").is_file()


def test_e2e_source_audit_failure_publishes_nothing(tmp_path, pdf_factory, fake_docling):
    class FailingAuditAI(FakeAIRunner):
        def audit_source(self, state, language_decision):
            return {"passed": False, "issues": ["Source inventory mismatch"]}

    pdf_factory(tmp_path / "unsafe.pdf", "Source Audit Gate Research", language="en")
    result = skill.convert_research_papers(
        str(tmp_path / "unsafe.pdf"),
        ai_runner=FailingAuditAI(),
        docling_engine=fake_docling,
        workspace_root=tmp_path,
    )
    assert result["status"] == "error"
    output = tmp_path / "Source Audit Gate Research"
    assert (tmp_path / "Source Audit Gate Research.pdf").is_file()
    assert not (output / "original.md").exists()
    assert not (output / "vie.md").exists()
    assert not (output / ".conversion-manifest.json").exists()
