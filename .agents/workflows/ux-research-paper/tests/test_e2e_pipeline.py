from __future__ import annotations

import sys
from pathlib import Path

import pytest


WORKFLOW = Path(__file__).resolve().parents[1]
CONVERTER_SCRIPTS = WORKFLOW / "skills" / "convert-researchpaper-to-md" / "scripts"
TRANSLATOR_SCRIPTS = WORKFLOW / "skills" / "translate-to-vie" / "scripts"
sys.path[:0] = [str(CONVERTER_SCRIPTS), str(TRANSLATOR_SCRIPTS)]

import convert_researchpaper_to_md as converter  # noqa: E402
import translate_to_vie as translator  # noqa: E402


class WorkflowDocling:
    @staticmethod
    def _metadata(path):
        values = {}
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                values[key] = value
        return values

    def preflight(self, source, job_dir):
        title = self._metadata(source)["TITLE"]
        candidate = {"label": "title", "content_layer": "body", "text": title, "page_no": 1}
        job_dir.mkdir(parents=True, exist_ok=True)
        return converter.PreflightBundle([candidate], candidate, None, "2.117.0-workflow-test", "SUCCESS", 1, True)

    def convert(self, source, staging_dir):
        metadata = self._metadata(source)
        if metadata.get("PARTIAL") == "yes":
            raise converter.SkillError("DOCLING_PARTIAL_SUCCESS", "Fixture partial conversion.")
        staging_dir.mkdir(parents=True, exist_ok=True)
        asset_dir = staging_dir / "Asset"
        asset_dir.mkdir()
        asset = asset_dir / "page-001-figure-001.png"
        asset.write_bytes(b"workflow-image")
        original = f"""# {metadata['TITLE']}

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
        converter.atomic_write_text(staging_dir / "original.md", original)
        inventory = {"page_count": 1, "items": [], "asset_count": 1}
        converter.atomic_write_json(staging_dir / "lossless-docling.json", {"docling": {}, "normalized": inventory})
        assets = [{"path": "Asset/page-001-figure-001.png", "kind": "picture", "page_no": 1, "sha256": converter.sha256_file(asset)}]
        return converter.ConversionBundle("SUCCESS", "2.117.0-workflow-test", 1, assets, inventory, [])


class WorkflowConverterAI:
    def __init__(self, confidence=0.99):
        self.confidence = confidence

    def validate_title(self, preflight):
        return {
            "valid": self.confidence >= converter.MIN_TITLE_CONFIDENCE,
            "confidence": self.confidence,
            "title": preflight["selected_candidate"]["text"],
            "reason": "Workflow fixture title.",
        }

    def detect_language(self, state):
        return {"language": "en", "confidence": 0.99, "reason": "Workflow fixture language."}

    def audit_source(self, state, language_decision):
        return {
            "passed": True,
            "issues": [],
            "chunk_ids": state["source_audit_plan"]["chunk_ids"],
            "coverage_complete": True,
        }


def _pdf(path, title, *, partial=False):
    path.write_bytes(
        (f"%PDF-1.4\nTITLE:{title}\nLANG:en\nPARTIAL:{'yes' if partial else 'no'}\n%%EOF\n").encode("utf-8")
    )
    return path


def _voice(resolved, blocks):
    return {
        "schema_version": translator.VOICE_SCHEMA_VERSION,
        "language": "vi",
        "source_sha256": resolved["source_sha256"],
        "original_md_sha256": resolved["original_md_sha256"],
        "source_block_ids": [block.block_id for block in blocks],
        "profile": {
            "ngoi_ke": "Giọng văn nghiên cứu ở ngôi thứ nhất số nhiều.",
            "muc_do_trang_trong": "Trang trọng và chính xác.",
            "lap_truong_hoc_thuat": "Khách quan, dựa trên bằng chứng.",
            "muc_do_chac_chan": "Thận trọng trong suy luận.",
            "nhip_va_cau_truc_cau": "Câu logic với nhịp vừa phải.",
            "mat_do_dien_dat": "Mật độ thông tin cao.",
            "van_phong_chuyen_nganh": "Thuật ngữ AI nhất quán.",
            "lap_luan_va_bang_chung": "Trình bày dữ liệu trước kết luận.",
        },
        "translation_rules": ["Dịch đầy đủ và giữ giọng văn học thuật.", "Không thay đổi cấu trúc Markdown."],
        "preferred_terms": [{"source_term": "participants", "vietnamese": "người tham gia", "note": "Dùng nhất quán."}],
        "protected_content_rules": ["Không được thay đổi DOI, URL, số, đơn vị, mã hoặc trích dẫn."],
    }


def _translation(resolved, blocks):
    replacements = {
        "# Workflow Research Paper": "# Bài nghiên cứu quy trình",
        "## Abstract": "## Tóm tắt",
        "We studied 42 participants [1] using the AI system.": "Chúng tôi nghiên cứu 42 người tham gia [1] bằng hệ thống AI.",
        "## Method": "## Phương pháp",
        "The method preserves DOI 10.1234/example, `model_id`, and unit 5 kg.": "Phương pháp giữ nguyên DOI 10.1234/example, `model_id` và đơn vị 5 kg.",
        "| Measure | Value |": "| Chỉ số | Giá trị |",
        "| Sample | 42 |": "| Mẫu | 42 |",
        "![Figure 1](Asset/page-001-figure-001.png)": "![Hình 1](Asset/page-001-figure-001.png)",
        "## References": "## Tài liệu tham khảo",
    }
    return {
        "schema_version": translator.TRANSLATION_SCHEMA_VERSION,
        "source_sha256": resolved["source_sha256"],
        "original_md_sha256": resolved["original_md_sha256"],
        "blocks": [
            {"block_id": block.block_id, "kind": block.kind, "translated_text": replacements.get(block.raw, block.raw)}
            for block in blocks
            if block.translatable
        ],
    }


def _audit(resolved):
    return {
        "schema_version": translator.AUDIT_SCHEMA_VERSION,
        "source_sha256": resolved["source_sha256"],
        "original_md_sha256": resolved["original_md_sha256"],
        "passed": True,
        "issues": [],
    }


def _convert(root, source):
    return converter.convert_research_papers(
        str(source),
        ai_runner=WorkflowConverterAI(),
        docling_engine=WorkflowDocling(),
        workspace_root=root,
    )


def test_e2e_pipeline_pauses_then_translates_after_exact_approval(tmp_path):
    source = _pdf(tmp_path / "unknown.pdf", "Workflow Research Paper")
    converted = _convert(tmp_path, source)
    assert converted["status"] == "success"
    item = converted["results"][0]
    assert Path(item["original_md"]).is_file()
    assert not (Path(item["output_dir"]) / "vie.md").exists()

    resolved = translator.resolve_converted_paper(str(source), converted, workspace_root=tmp_path)
    approval = translator.create_approval_state(resolved, workspace_root=tmp_path, run_id="workflow-approval")
    assert approval["status"] == "awaiting_approval"
    assert not (Path(item["output_dir"]) / "voice-tone.md").exists()

    prepared = translator.prepare_translation(
        Path(approval["approval_state"]),
        "approve " + approval["approval_token"],
        workspace_root=tmp_path,
    )
    blocks = translator.parse_markdown_blocks(Path(item["original_md"]).read_text(encoding="utf-8"))
    voiced = translator.build_voice_tone(Path(prepared["state_path"]), _voice(resolved, blocks))
    translated = translator.build_translation(Path(voiced["state_path"]), _translation(resolved, blocks))
    result = translator.publish_translation(Path(translated["state_path"]), _audit(resolved))

    assert result["status"] == "success"
    assert Path(result["voice_tone_md"]).is_file()
    assert Path(result["vie_md"]).is_file()
    translator.validate_markdown_parity(
        Path(item["original_md"]).read_text(encoding="utf-8"),
        Path(result["vie_md"]).read_text(encoding="utf-8"),
    )
    assert not Path(approval["approval_state"]).exists()
    assert not Path(prepared["staging_dir"]).exists()


def test_e2e_changed_original_invalidates_approval(tmp_path):
    source = _pdf(tmp_path / "unknown.pdf", "Workflow Research Paper")
    converted = _convert(tmp_path, source)
    resolved = translator.resolve_converted_paper(str(source), converted, workspace_root=tmp_path)
    approval = translator.create_approval_state(resolved, workspace_root=tmp_path, run_id="changed-approval")
    Path(resolved["original_md"]).write_text("changed", encoding="utf-8")
    with pytest.raises(translator.SkillError) as caught:
        translator.prepare_translation(
            Path(approval["approval_state"]),
            "approve " + approval["approval_token"],
            workspace_root=tmp_path,
        )
    assert caught.value.code == "APPROVAL_INVALID"
    assert not Path(approval["approval_state"]).exists()


def test_e2e_existing_output_denies_replacement(tmp_path):
    source = _pdf(tmp_path / "unknown.pdf", "Workflow Research Paper")
    converted = _convert(tmp_path, source)
    resolved = translator.resolve_converted_paper(str(source), converted, workspace_root=tmp_path)
    existing = Path(resolved["paper_folder"]) / "vie.md"
    existing.write_text("existing user translation", encoding="utf-8")
    with pytest.raises(translator.SkillError) as caught:
        translator.create_approval_state(resolved, workspace_root=tmp_path, run_id="existing-output")
    assert caught.value.code == "OUTPUT_EXISTS"
    assert existing.read_text(encoding="utf-8") == "existing user translation"


def test_e2e_converter_failure_prevents_translation(tmp_path):
    source = _pdf(tmp_path / "partial.pdf", "Incomplete Workflow Paper", partial=True)
    converted = _convert(tmp_path, source)
    assert converted["status"] == "error"
    with pytest.raises(translator.SkillError) as caught:
        translator.resolve_converted_paper(str(source), converted, workspace_root=tmp_path)
    assert caught.value.code == "CONVERSION_NOT_SUCCESSFUL"


def test_e2e_prior_handoff_skips_before_obsolete_source_rediscovery(tmp_path):
    source = _pdf(tmp_path / "unknown.pdf", "Workflow Research Paper")
    converted = _convert(tmp_path, source)
    assert converted["status"] == "success"
    assert not source.exists()
    resumed = converter.convert_research_papers(
        str(source),
        prior_handoff=converted,
        ai_runner=None,
        workspace_root=tmp_path,
    )
    assert resumed["status"] == "success"
    assert resumed["source_type"] == "prior_handoff"
    assert resumed["results"][0]["reason"] == "valid_prior_handoff"
