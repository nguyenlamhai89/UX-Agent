from __future__ import annotations

from pathlib import Path

import pytest

import translate_to_vie as skill
from conftest import audit_response, translation_response, voice_response


def _resolve(converted_paper, tmp_path):
    return skill.resolve_converted_paper(
        converted_paper["url_path"],
        converted_paper["handoff"],
        workspace_root=tmp_path,
    )


def _prepare(converted_paper, tmp_path, *, budget=None):
    resolved = _resolve(converted_paper, tmp_path)
    approval = skill.create_approval_state(resolved, workspace_root=tmp_path, run_id="approval-run")
    prepared = skill.prepare_translation(
        Path(approval["approval_state"]),
        "approve " + approval["approval_token"],
        workspace_root=tmp_path,
        budget=budget,
    )
    return resolved, approval, prepared


def test_resolve_and_create_hash_bound_approval(converted_paper, tmp_path):
    resolved = _resolve(converted_paper, tmp_path)
    approval = skill.create_approval_state(resolved, workspace_root=tmp_path, run_id="approval-run")
    assert approval["status"] == "awaiting_approval"
    assert approval["approval_token"].startswith("APPROVE-TRANSLATE-TO-VIE:")
    assert Path(approval["approval_state"]).is_file()
    assert not (converted_paper["paper_folder"] / "voice-tone.md").exists()
    assert not (converted_paper["paper_folder"] / "vie.md").exists()


def test_multiple_converter_results_are_rejected(converted_paper, tmp_path):
    handoff = dict(converted_paper["handoff"])
    handoff["pdf_count"] = 2
    handoff["results"] = handoff["results"] * 2
    with pytest.raises(skill.SkillError) as caught:
        skill.resolve_converted_paper(converted_paper["url_path"], handoff, workspace_root=tmp_path)
    assert caught.value.code == "MULTIPLE_PDFS_DISCOVERED"


def test_approval_requires_affirmative_response_and_exact_token(converted_paper, tmp_path):
    resolved = _resolve(converted_paper, tmp_path)
    approval = skill.create_approval_state(resolved, workspace_root=tmp_path, run_id="approval-run")
    with pytest.raises(skill.SkillError) as caught:
        skill.prepare_translation(Path(approval["approval_state"]), "yes", workspace_root=tmp_path)
    assert caught.value.code == "NOT_APPROVED"
    assert Path(approval["approval_state"]).is_file()


def test_changed_original_invalidates_and_removes_approval(converted_paper, tmp_path):
    resolved = _resolve(converted_paper, tmp_path)
    approval = skill.create_approval_state(resolved, workspace_root=tmp_path, run_id="approval-run")
    converted_paper["original_md"].write_text("changed after approval", encoding="utf-8")
    with pytest.raises(skill.SkillError) as caught:
        skill.prepare_translation(
            Path(approval["approval_state"]),
            "approve " + approval["approval_token"],
            workspace_root=tmp_path,
        )
    assert caught.value.code == "APPROVAL_INVALID"
    assert not Path(approval["approval_state"]).exists()


@pytest.mark.parametrize("filename", ["voice-tone.md", "vie.md"])
def test_existing_output_denies_replacement_before_ai(converted_paper, tmp_path, filename):
    resolved = _resolve(converted_paper, tmp_path)
    target = converted_paper["paper_folder"] / filename
    target.write_text("existing", encoding="utf-8")
    with pytest.raises(skill.SkillError) as caught:
        skill.create_approval_state(resolved, workspace_root=tmp_path, run_id="approval-run")
    assert caught.value.code == "OUTPUT_EXISTS"
    assert target.read_text(encoding="utf-8") == "existing"


def test_voice_tone_requires_complete_ordered_block_coverage(converted_paper, tmp_path):
    resolved, approval, prepared = _prepare(converted_paper, tmp_path)
    blocks = skill.parse_markdown_blocks(converted_paper["original_md"].read_text(encoding="utf-8"))
    response = voice_response(resolved, blocks)
    response["source_block_ids"] = response["source_block_ids"][:-1]
    with pytest.raises(skill.SkillError) as caught:
        skill.build_voice_tone(Path(prepared["state_path"]), response)
    assert caught.value.code == "VOICE_TONE_COVERAGE_FAILED"
    assert caught.value.details["retryable"] is True
    assert Path(prepared["staging_dir"]).exists()
    assert Path(approval["approval_state"]).exists()
    retried = skill.build_voice_tone(Path(prepared["state_path"]), voice_response(resolved, blocks))
    assert retried["status"] == "awaiting_translation"


def test_translation_rejects_changed_protected_number(converted_paper, tmp_path):
    resolved, _approval, prepared = _prepare(converted_paper, tmp_path)
    blocks = skill.parse_markdown_blocks(converted_paper["original_md"].read_text(encoding="utf-8"))
    voiced = skill.build_voice_tone(Path(prepared["state_path"]), voice_response(resolved, blocks))
    response = translation_response(resolved, blocks)
    target = next(item for item in response["blocks"] if "42" in item["translated_text"])
    target["translated_text"] = target["translated_text"].replace("42", "41")
    with pytest.raises(skill.SkillError) as caught:
        skill.build_translation(Path(voiced["state_path"]), response)
    assert caught.value.code == "PROTECTED_TOKEN_CHANGED"


def test_markdown_parity_rejects_heading_level_change():
    original = "# Title\n\n## Method\n\n42 participants.\n"
    vietnamese = "# Tiêu đề\n\n### Phương pháp\n\n42 người tham gia.\n"
    with pytest.raises(skill.SkillError) as caught:
        skill.validate_markdown_parity(original, vietnamese)
    assert caught.value.code == "MARKDOWN_STRUCTURE_MISMATCH"


def test_cleanup_rejects_empty_or_unowned_paths(tmp_path):
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    skill._cleanup_state(
        {
            "workspace_root": str(tmp_path),
            "resolved": {"paper_folder": str(tmp_path / "paper")},
            "staging_dir": "",
            "approval_state": "",
        }
    )
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert tmp_path.is_dir()


def test_voice_request_uses_file_references_instead_of_full_document(converted_paper, tmp_path):
    _resolved, _approval, prepared = _prepare(converted_paper, tmp_path)
    request = skill.read_json(Path(prepared["voice_tone_request"]))
    assert isinstance(request["original_md"], dict)
    assert request["original_md"]["path"] == str(converted_paper["original_md"])
    assert request["original_md"]["sha256"] == skill.sha256_file(converted_paper["original_md"])
    assert isinstance(request["block_inventory"], dict)
    assert "blocks" not in request
    assert "We studied 42 participants" not in Path(prepared["voice_tone_request"]).read_text(encoding="utf-8")


def test_translation_chunks_are_bounded_resumable_and_parallel_safe(converted_paper, tmp_path):
    budget = skill.TranslationBudget(max_blocks_per_chunk=2, max_chars_per_chunk=500)
    resolved, _approval, prepared = _prepare(converted_paper, tmp_path, budget=budget)
    blocks = skill.parse_markdown_blocks(converted_paper["original_md"].read_text(encoding="utf-8"))
    voiced = skill.build_voice_tone(Path(prepared["state_path"]), voice_response(resolved, blocks))
    chunks = voiced["translation_chunks"]
    assert len(chunks) > 1
    plan = skill.read_json(Path(voiced["translation_chunk_plan"]["path"]))
    assert plan["parallel_safe"] is True
    assert all(len(chunk["block_ids"]) <= 2 for chunk in chunks)

    full = translation_response(resolved, blocks)
    first = chunks[0]
    first_response = dict(full)
    first_response["chunk_id"] = first["chunk_id"]
    first_response["blocks"] = [item for item in full["blocks"] if item["block_id"] in first["block_ids"]]
    partial = skill.build_translation(Path(voiced["state_path"]), first_response)
    assert partial["status"] == "awaiting_translation"
    assert Path(first["response"]).is_file()

    second = chunks[1]
    malformed = dict(full)
    malformed["chunk_id"] = second["chunk_id"]
    malformed["blocks"] = []
    with pytest.raises(skill.SkillError) as caught:
        skill.build_translation(Path(partial["state_path"]), malformed)
    assert caught.value.details["retryable"] is True
    resumed = skill.read_json(Path(partial["state_path"]))
    assert resumed["translation_chunks"][0]["completed"] is True
    assert Path(first["response"]).is_file()


def test_ai_retry_budget_is_bounded_and_cleans_after_exhaustion(converted_paper, tmp_path):
    resolved, approval, prepared = _prepare(
        converted_paper,
        tmp_path,
        budget=skill.TranslationBudget(max_ai_attempts=3),
    )
    blocks = skill.parse_markdown_blocks(converted_paper["original_md"].read_text(encoding="utf-8"))
    invalid = voice_response(resolved, blocks)
    invalid["source_block_ids"] = []
    for attempt in range(1, 4):
        with pytest.raises(skill.SkillError) as caught:
            skill.build_voice_tone(Path(prepared["state_path"]), invalid)
        assert caught.value.details["attempt"] == attempt
    assert caught.value.details["retry_exhausted"] is True
    assert not Path(prepared["staging_dir"]).exists()
    assert not Path(approval["approval_state"]).exists()


def test_markdown_parser_covers_complex_commonmark_and_crlf():
    original = (
        "Research title\r\n=====\r\n\r\n"
        "| Escaped \\| label | Value |\r\n| --- | --- |\r\n"
        "- First item\r\n  continuation text\r\n\r\n"
        "<section>\r\nInside HTML block.\r\n</section>\r\n\r\n"
        "$$\r\nx = 42\r\n$$\r\n\r\n"
        "[paper]: https://example.org/paper \"Paper\"\r\n"
    )
    blocks = skill.parse_markdown_blocks(original)
    kinds = [block.kind for block in blocks]
    assert "setext_heading" in kinds
    assert "setext_underline" in kinds
    assert "list_continuation" in kinds
    assert "html_block" in kinds
    assert "math_block" in kinds
    assert "reference_definition" in kinds
    replacements = {
        "Research title": "Tiêu đề nghiên cứu",
        "| Escaped \\| label | Value |": "| Nhãn \\| đã thoát | Giá trị |",
        "- First item": "- Mục đầu tiên",
        "  continuation text": "  nội dung tiếp nối",
        "Inside HTML block.": "Nội dung trong khối HTML.",
    }
    translated = skill.reassemble_markdown(
        original,
        blocks,
        {block.block_id: replacements[block.raw] for block in blocks if block.raw in replacements},
    )
    skill.validate_markdown_parity(original, translated)
    assert "\r\n" in translated


def test_translation_budget_rejects_oversized_source_before_ai(converted_paper, tmp_path):
    resolved = _resolve(converted_paper, tmp_path)
    approval = skill.create_approval_state(resolved, workspace_root=tmp_path, run_id="budget-approval")
    with pytest.raises(skill.SkillError) as caught:
        skill.prepare_translation(
            Path(approval["approval_state"]),
            "approve " + approval["approval_token"],
            workspace_root=tmp_path,
            budget=skill.TranslationBudget(max_source_chars=10),
        )
    assert caught.value.code == "RESOURCE_REVIEW_REQUIRED"
    assert skill.read_json(Path(approval["approval_state"]))["status"] == "awaiting_approval"


def test_translation_budget_enforces_estimated_token_limit(converted_paper, tmp_path):
    resolved = _resolve(converted_paper, tmp_path)
    approval = skill.create_approval_state(resolved, workspace_root=tmp_path, run_id="token-budget-approval")
    with pytest.raises(skill.SkillError) as caught:
        skill.prepare_translation(
            Path(approval["approval_state"]),
            "approve " + approval["approval_token"],
            workspace_root=tmp_path,
            budget=skill.TranslationBudget(max_estimated_tokens=1),
        )
    assert caught.value.code == "RESOURCE_REVIEW_REQUIRED"
    assert caught.value.details["estimated_tokens"] > caught.value.details["max_estimated_tokens"]


def test_audit_request_is_compact_and_references_staged_files(converted_paper, tmp_path):
    resolved, _approval, prepared = _prepare(converted_paper, tmp_path)
    blocks = skill.parse_markdown_blocks(converted_paper["original_md"].read_text(encoding="utf-8"))
    voiced = skill.build_voice_tone(Path(prepared["state_path"]), voice_response(resolved, blocks))
    translated = skill.build_translation(Path(voiced["state_path"]), translation_response(resolved, blocks))
    request_path = Path(translated["staging_dir"]) / "audit-request.json"
    request = skill.read_json(request_path)
    for field in ("original_md", "voice_tone_md", "vie_md", "audit_inventory"):
        assert set(request[field]) == {"path", "sha256"}
        assert Path(request[field]["path"]).is_file()
        assert skill.sha256_file(Path(request[field]["path"])) == request[field]["sha256"]
    serialized = request_path.read_text(encoding="utf-8")
    assert "We studied 42 participants" not in serialized
    assert "Chúng tôi nghiên cứu 42 người tham gia" not in serialized


def test_complete_translation_pipeline_publishes_both_outputs(converted_paper, tmp_path):
    resolved, approval, prepared = _prepare(converted_paper, tmp_path)
    blocks = skill.parse_markdown_blocks(converted_paper["original_md"].read_text(encoding="utf-8"))
    voiced = skill.build_voice_tone(Path(prepared["state_path"]), voice_response(resolved, blocks))
    translated = skill.build_translation(Path(voiced["state_path"]), translation_response(resolved, blocks))
    result = skill.publish_translation(Path(translated["state_path"]), audit_response(resolved))
    assert result["status"] == "success"
    assert Path(result["voice_tone_md"]).is_file()
    assert Path(result["vie_md"]).is_file()
    assert "## Phương pháp" in Path(result["vie_md"]).read_text(encoding="utf-8")
    assert not Path(approval["approval_state"]).exists()
    assert not Path(prepared["staging_dir"]).exists()
