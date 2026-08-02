from __future__ import annotations

from pathlib import Path

import pytest

import translate_to_vie as skill
from conftest import audit_response, create_converter_output, translation_response, voice_response


def _approved_state(paper, root, run_id):
    resolved = skill.resolve_converted_paper(paper["url_path"], paper["handoff"], workspace_root=root)
    approval = skill.create_approval_state(resolved, workspace_root=root, run_id=run_id)
    prepared = skill.prepare_translation(
        Path(approval["approval_state"]),
        "approved " + approval["approval_token"],
        workspace_root=root,
    )
    return resolved, approval, prepared


def test_e2e_vietnamese_source_is_copied_byte_for_byte(tmp_path):
    paper = create_converter_output(tmp_path, language="vi", title="Đánh giá AI đáng tin cậy")
    resolved, approval, prepared = _approved_state(paper, tmp_path, "vi-approval")
    blocks = skill.parse_markdown_blocks(paper["original_md"].read_text(encoding="utf-8"))
    voiced = skill.build_voice_tone(Path(prepared["state_path"]), voice_response(resolved, blocks))
    assert voiced["status"] == "awaiting_audit"
    result = skill.publish_translation(Path(voiced["state_path"]), audit_response(resolved))
    assert result["copied_source"] is True
    assert Path(result["vie_md"]).read_bytes() == paper["original_md"].read_bytes()
    assert Path(result["voice_tone_md"]).is_file()
    assert not Path(approval["approval_state"]).exists()


def test_e2e_audit_failure_publishes_nothing(tmp_path):
    paper = create_converter_output(tmp_path)
    resolved, _approval, prepared = _approved_state(paper, tmp_path, "audit-approval")
    blocks = skill.parse_markdown_blocks(paper["original_md"].read_text(encoding="utf-8"))
    voiced = skill.build_voice_tone(Path(prepared["state_path"]), voice_response(resolved, blocks))
    translated = skill.build_translation(Path(voiced["state_path"]), translation_response(resolved, blocks))
    audit = audit_response(resolved)
    audit["passed"] = False
    audit["issues"] = ["Missing nuance"]
    with pytest.raises(skill.SkillError) as caught:
        skill.publish_translation(Path(translated["state_path"]), audit)
    assert caught.value.code == "AI_AUDIT_FAILED"
    assert caught.value.details["retryable"] is True
    assert caught.value.details["resume_status"] == "awaiting_translation"
    assert not (paper["paper_folder"] / "voice-tone.md").exists()
    assert not (paper["paper_folder"] / "vie.md").exists()
    assert Path(prepared["staging_dir"]).exists()
    resumed = skill.read_json(Path(prepared["state_path"]))
    assert resumed["status"] == "awaiting_translation"
    assert all(not chunk["completed"] for chunk in resumed["translation_chunks"])
    translated = skill.build_translation(Path(prepared["state_path"]), translation_response(resolved, blocks))
    result = skill.publish_translation(Path(translated["state_path"]), audit_response(resolved))
    assert result["status"] == "success"


def test_e2e_second_output_failure_rolls_back_first(tmp_path, monkeypatch):
    paper = create_converter_output(tmp_path)
    resolved, _approval, prepared = _approved_state(paper, tmp_path, "rollback-approval")
    blocks = skill.parse_markdown_blocks(paper["original_md"].read_text(encoding="utf-8"))
    voiced = skill.build_voice_tone(Path(prepared["state_path"]), voice_response(resolved, blocks))
    translated = skill.build_translation(Path(voiced["state_path"]), translation_response(resolved, blocks))
    original_writer = skill._exclusive_write_bytes

    def fail_second(path, data):
        if Path(path).name == "vie.md":
            raise OSError("simulated second-file failure")
        return original_writer(path, data)

    monkeypatch.setattr(skill, "_exclusive_write_bytes", fail_second)
    with pytest.raises(skill.SkillError) as caught:
        skill.publish_translation(Path(translated["state_path"]), audit_response(resolved))
    assert caught.value.code == "PUBLICATION_FAILED"
    assert not (paper["paper_folder"] / "voice-tone.md").exists()
    assert not (paper["paper_folder"] / "vie.md").exists()
