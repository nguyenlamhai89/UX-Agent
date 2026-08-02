from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

import convert_researchpaper_to_md as skill
from conftest import FakeAIRunner, FakeHttpClient


def test_select_title_prefers_body_title_and_excludes_furniture():
    items = [
        {"label": "title", "content_layer": "furniture", "text": "Journal of Testing"},
        {"label": "section_header", "content_layer": "body", "text": "Introduction"},
        {"label": "title", "content_layer": "body", "text": "A Reliable Research Title"},
    ]
    assert skill.select_title_candidate(items)["text"] == "A Reliable Research Title"


def test_select_title_falls_back_to_first_real_section_heading():
    items = [
        {"label": "section_header", "content_layer": "body", "text": "Abstract"},
        {"label": "section_header", "content_layer": "body", "text": "Human Factors in AI Review"},
    ]
    assert skill.select_title_candidate(items)["text"] == "Human Factors in AI Review"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("  A / Study: With? Unsafe* Characters  ", "A Study With Unsafe Characters"),
        ("Đánh giá trải nghiệm người dùng", "Đánh giá trải nghiệm người dùng"),
        ("CON", "Paper - CON"),
    ],
)
def test_safe_title_stem(raw, expected):
    assert skill.safe_title_stem(raw) == expected


def test_discover_local_directory_is_non_recursive_and_deterministic(tmp_path, pdf_factory):
    pdf_factory(tmp_path / "b.PDF", "Second")
    pdf_factory(tmp_path / "A.pdf", "First")
    nested = tmp_path / "nested"
    nested.mkdir()
    pdf_factory(nested / "ignored.pdf", "Ignored")
    result = skill.discover_sources(str(tmp_path), workspace_root=tmp_path)
    assert [item["original_name"] for item in result["sources"]] == ["A.pdf", "b.PDF"]


def test_discover_rejects_relative_local_path(tmp_path):
    with pytest.raises(skill.SkillError) as caught:
        skill.discover_sources("papers", workspace_root=tmp_path)
    assert caught.value.code == "INVALID_INPUT"


def test_low_confidence_title_never_renames_or_creates_title_folder(tmp_path, pdf_factory, fake_docling):
    source = pdf_factory(tmp_path / "arbitrary.pdf", "Reliable Paper Title")
    result = skill.convert_research_papers(
        str(source),
        ai_runner=FakeAIRunner(title_confidence=0.3),
        docling_engine=fake_docling,
        workspace_root=tmp_path,
    )
    assert result["status"] == "review_required"
    assert source.exists()
    assert not (tmp_path / "Reliable Paper Title.pdf").exists()
    assert not (tmp_path / "Reliable Paper Title").exists()


def test_remote_pdf_uses_workspace_output_and_persists_renamed_copy(tmp_path, fake_docling, fake_ai):
    url = "https://papers.example/research.pdf"
    data = b"%PDF-1.4\nTITLE:Remote Research Title\nLANG:en\nPARTIAL:no\n%%EOF\n"
    client = FakeHttpClient({url: (url, "application/pdf", data)})
    output_root = tmp_path / "output" / "convert-researchpaper-to-md"
    result = skill.convert_research_papers(
        url,
        output_root=output_root,
        ai_runner=fake_ai,
        http_client=client,
        docling_engine=fake_docling,
        workspace_root=tmp_path,
    )
    assert result["status"] == "success"
    assert (output_root / "Remote Research Title.pdf").is_file()
    assert (output_root / "Remote Research Title" / "original.md").is_file()
    incoming = tmp_path / ".agents/scratch/convert-researchpaper-to-md/incoming"
    assert not incoming.exists() or not any(incoming.iterdir())


def test_discovery_uses_streaming_client_without_buffered_fetch(tmp_path):
    url = "https://papers.example/streamed.pdf"
    data = b"%PDF-1.4\nTITLE:Streamed Paper\n%%EOF\n"

    class StreamingClient:
        fetch_called = False

        def fetch(self, _url, _max_bytes):
            self.fetch_called = True
            raise AssertionError("buffered fetch must not be used")

        def fetch_to_path(self, requested, max_bytes, destination):
            assert requested == url
            assert len(data) <= max_bytes
            destination.write_bytes(data)
            return requested, "application/pdf", skill.sha256_bytes(data), len(data)

    client = StreamingClient()
    result = skill.discover_sources(url, workspace_root=tmp_path, http_client=client)
    assert result["pdf_count"] == 1
    assert Path(result["sources"][0]["local_path"]).read_bytes() == data
    assert client.fetch_called is False


def test_http_client_retries_transient_503_and_streams_to_disk(tmp_path, monkeypatch):
    data = b"%PDF-1.4\n%%EOF\n"
    attempts = []
    sleeps = []

    class Headers(dict):
        def get_content_type(self):
            return "application/pdf"

    class Response:
        headers = Headers({"Content-Length": str(len(data))})

        def __init__(self):
            self.offset = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return "https://papers.example/retry.pdf"

        def read(self, size):
            chunk = data[self.offset : self.offset + size]
            self.offset += len(chunk)
            return chunk

    def urlopen(_request, timeout):
        attempts.append(timeout)
        if len(attempts) == 1:
            raise urllib.error.HTTPError("https://papers.example/retry.pdf", 503, "busy", {}, None)
        return Response()

    monkeypatch.setattr(skill, "_reject_unsafe_remote_host", lambda _url: None)
    monkeypatch.setattr(skill.urllib.request, "urlopen", urlopen)
    client = skill.UrllibHttpClient(max_attempts=3, retry_base_seconds=0.01, sleep_fn=sleeps.append)
    destination = tmp_path / "retry.part"
    final_url, content_type, digest, size = client.fetch_to_path(
        "https://papers.example/retry.pdf", len(data), destination
    )
    assert len(attempts) == 2
    assert sleeps == [0.01]
    assert final_url.endswith("retry.pdf")
    assert content_type == "application/pdf"
    assert digest == skill.sha256_bytes(data)
    assert size == len(data)
    assert destination.read_bytes() == data


def test_remote_title_rename_happens_before_output_parent_creation(tmp_path, fake_docling, monkeypatch):
    url = "https://papers.example/ordering.pdf"
    data = b"%PDF-1.4\nTITLE:Remote Ordering Study\nLANG:en\nPARTIAL:no\n%%EOF\n"
    client = FakeHttpClient({url: (url, "application/pdf", data)})
    discovery = skill.discover_sources(url, workspace_root=tmp_path, http_client=client)
    record = skill.SourceRecord(**discovery["sources"][0])
    preflight = skill.run_preflight(record, docling_engine=fake_docling, workspace_root=tmp_path)
    output_root = tmp_path / "output" / "convert-researchpaper-to-md"
    original_rename = skill._rename_source
    observed = []

    def assert_order(source, target, expected_hash):
        observed.append((Path(source), Path(target)))
        assert not output_root.exists()
        return original_rename(source, target, expected_hash)

    monkeypatch.setattr(skill, "_rename_source", assert_order)
    state = skill.prepare_paper(
        preflight,
        {"valid": True, "confidence": 0.99, "title": "Remote Ordering Study"},
        output_root=output_root,
        docling_engine=fake_docling,
        workspace_root=tmp_path,
    )
    assert observed
    assert observed[0][1].parent == observed[0][0].parent
    assert Path(state["renamed_pdf"]).parent == output_root


def test_partial_docling_failure_keeps_successful_rename_but_no_final_markdown(tmp_path, pdf_factory, fake_docling, fake_ai):
    source = pdf_factory(tmp_path / "partial.pdf", "Partially Parsed Paper", partial=True)
    result = skill.convert_research_papers(
        str(source),
        ai_runner=fake_ai,
        docling_engine=fake_docling,
        workspace_root=tmp_path,
    )
    assert result["status"] == "error"
    renamed = tmp_path / "Partially Parsed Paper.pdf"
    folder = tmp_path / "Partially Parsed Paper"
    assert renamed.is_file()
    assert folder.is_dir()
    assert not (folder / "original.md").exists()
    assert not (folder / ".conversion-manifest.json").exists()


def test_manifest_validation_detects_tampering(tmp_path, pdf_factory, fake_docling, fake_ai):
    source = pdf_factory(tmp_path / "paper.pdf", "Manifest Integrity Study")
    first = skill.convert_research_papers(
        str(source),
        ai_runner=fake_ai,
        docling_engine=fake_docling,
        workspace_root=tmp_path,
    )
    assert first["status"] == "success"
    output = tmp_path / "Manifest Integrity Study"
    assert skill.inspect_output(output)["status"] == "valid"
    manifest = json.loads((output / ".conversion-manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == skill.MANIFEST_SCHEMA_VERSION
    assert manifest["original_md"] == str(output / "original.md")
    assert manifest["paper_folder"] == str(output)
    assert manifest["original_md_sha256"] == skill.sha256_file(output / "original.md")
    assert not (output / "vie.md").exists()
    (output / "original.md").write_text("tampered", encoding="utf-8")
    assert skill.inspect_output(output)["status"] == "invalid"


def test_valid_prior_handoff_skips_before_discovery_docling_and_ai(tmp_path, pdf_factory, fake_docling, fake_ai):
    source = pdf_factory(tmp_path / "paper.pdf", "Early Handoff Skip")
    first = skill.convert_research_papers(
        str(source),
        ai_runner=fake_ai,
        docling_engine=fake_docling,
        workspace_root=tmp_path,
    )
    assert first["status"] == "success"
    assert not source.exists(), "the original direct path is intentionally obsolete after title rename"
    second = skill.convert_research_papers(
        str(source),
        prior_handoff=first,
        ai_runner=None,
        workspace_root=tmp_path,
    )
    assert second["status"] == "success"
    assert second["source_type"] == "prior_handoff"
    assert second["results"][0]["status"] == "skipped"


def test_page_budget_stops_before_rename_or_full_conversion(tmp_path, pdf_factory, fake_docling):
    source = pdf_factory(tmp_path / "paper.pdf", "Oversized Page Count")
    discovery = skill.discover_sources(str(source), workspace_root=tmp_path)
    record = skill.SourceRecord(**discovery["sources"][0])
    preflight = skill.run_preflight(record, docling_engine=fake_docling, workspace_root=tmp_path)
    preflight["page_count"] = 10
    preflight["page_count_complete"] = True
    with pytest.raises(skill.SkillError) as caught:
        skill.prepare_paper(
            preflight,
            {"valid": True, "confidence": 0.99, "title": "Oversized Page Count"},
            docling_engine=fake_docling,
            workspace_root=tmp_path,
            budget=skill.ResourceBudget(max_page_count=5),
        )
    assert caught.value.code == "RESOURCE_REVIEW_REQUIRED"
    assert caught.value.details["page_count"] == 10
    assert source.is_file()
    assert not (tmp_path / "Oversized Page Count").exists()


def test_source_audit_plan_is_chunked_and_requires_complete_coverage(tmp_path, pdf_factory, fake_docling):
    source = pdf_factory(tmp_path / "paper.pdf", "Chunked Source Audit")
    discovery = skill.discover_sources(str(source), workspace_root=tmp_path)
    record = skill.SourceRecord(**discovery["sources"][0])
    preflight = skill.run_preflight(record, docling_engine=fake_docling, workspace_root=tmp_path)
    state = skill.prepare_paper(
        preflight,
        {"valid": True, "confidence": 0.99, "title": "Chunked Source Audit"},
        docling_engine=fake_docling,
        workspace_root=tmp_path,
        budget=skill.ResourceBudget(audit_items_per_chunk=1),
    )
    assert state["source_audit_plan"]["chunk_count"] == 2
    with pytest.raises(skill.SkillError) as caught:
        skill.publish_paper(
            state,
            {"language": "en", "confidence": 0.99},
            {"passed": True, "issues": [], "chunk_ids": state["source_audit_plan"]["chunk_ids"][:1], "coverage_complete": True},
        )
    assert caught.value.code == "AI_AUDIT_FAILED"


def test_chunk_aware_ai_runner_audits_every_chunk_before_synthesis(tmp_path, pdf_factory, fake_docling):
    source = pdf_factory(tmp_path / "paper.pdf", "Chunk Synthesis")

    class ChunkAwareAI(FakeAIRunner):
        def __init__(self):
            super().__init__()
            self.audited = []

        def audit_source(self, state, language_decision):
            raise AssertionError("legacy single-context audit must not run")

        def audit_source_chunk(self, state, language_decision, chunk):
            self.audited.append(chunk["chunk_id"])
            return {"chunk_id": chunk["chunk_id"], "passed": True, "issues": []}

        def synthesize_source_audit(self, state, language_decision, chunk_results):
            return {
                "passed": all(item["passed"] for item in chunk_results),
                "issues": [],
                "chunk_ids": [item["chunk_id"] for item in chunk_results],
                "coverage_complete": True,
            }

    ai = ChunkAwareAI()
    result = skill.convert_research_papers(
        str(source),
        ai_runner=ai,
        docling_engine=fake_docling,
        workspace_root=tmp_path,
        budget=skill.ResourceBudget(audit_items_per_chunk=1),
    )
    assert result["status"] == "success"
    assert ai.audited == ["source-audit-0001", "source-audit-0002"]


def test_force_rebuild_preserves_translator_outputs(tmp_path, pdf_factory, fake_docling, fake_ai):
    source = pdf_factory(tmp_path / "paper.pdf", "Preserve Translator Outputs")
    first = skill.convert_research_papers(
        str(source),
        ai_runner=fake_ai,
        docling_engine=fake_docling,
        workspace_root=tmp_path,
    )
    assert first["status"] == "success"
    output = tmp_path / "Preserve Translator Outputs"
    (output / "voice-tone.md").write_text("voice", encoding="utf-8")
    (output / "vie.md").write_text("translation", encoding="utf-8")
    second = skill.convert_research_papers(
        str(tmp_path / "Preserve Translator Outputs.pdf"),
        force=True,
        ai_runner=fake_ai,
        docling_engine=fake_docling,
        workspace_root=tmp_path,
    )
    assert second["status"] == "success"
    assert (output / "voice-tone.md").read_text(encoding="utf-8") == "voice"
    assert (output / "vie.md").read_text(encoding="utf-8") == "translation"


def test_publication_rolls_back_existing_artifacts_if_manifest_commit_fails(
    tmp_path, pdf_factory, fake_docling, monkeypatch
):
    source = pdf_factory(tmp_path / "paper.pdf", "Rollback Safety Study")
    discovered = skill.discover_sources(str(source), workspace_root=tmp_path)
    record = skill.SourceRecord(**discovered["sources"][0])
    preflight = skill.run_preflight(record, docling_engine=fake_docling, workspace_root=tmp_path)
    state = skill.prepare_paper(
        preflight,
        {"valid": True, "confidence": 0.99, "title": "Rollback Safety Study"},
        docling_engine=fake_docling,
        workspace_root=tmp_path,
    )
    output = Path(state["output_dir"])
    (output / "original.md").write_text("prior original", encoding="utf-8")
    prior_asset = output / "Asset"
    prior_asset.mkdir()
    (prior_asset / "prior.png").write_bytes(b"prior")
    ai = FakeAIRunner()
    language = ai.detect_language(state)
    original_atomic_write_json = skill.atomic_write_json

    def fail_manifest(path, value):
        if Path(path).name == ".conversion-manifest.json":
            raise OSError("simulated commit failure")
        return original_atomic_write_json(path, value)

    monkeypatch.setattr(skill, "atomic_write_json", fail_manifest)
    with pytest.raises(skill.SkillError) as caught:
        skill.publish_paper(state, language, ai.audit_source(state, language))
    assert caught.value.code == "PUBLICATION_FAILED"
    assert (output / "original.md").read_text(encoding="utf-8") == "prior original"
    assert (output / "Asset" / "prior.png").read_bytes() == b"prior"


def test_dependency_report_is_actionable():
    report = skill.DoclingAdapter.dependency_report()
    if report["available"]:
        assert report["docling_version"]
    else:
        assert report["error_code"] in {"PYTHON_VERSION_UNSUPPORTED", "DOCLING_MISSING"}
        assert report["message"]


def test_docling_converter_configuration_matches_documented_pipeline_options():
    captured = {}

    class PipelineOptions:
        pass

    class TableOptions:
        def __init__(self, do_cell_matching):
            self.do_cell_matching = do_cell_matching

    class TesseractOptions:
        def __init__(self, lang, mode):
            self.lang = lang
            self.mode = mode

    class OcrMode:
        FULL_PAGE = "full_page"

    class InputFormat:
        PDF = "pdf"

    class PdfFormatOption:
        def __init__(self, pipeline_options):
            self.pipeline_options = pipeline_options

    class DocumentConverter:
        def __init__(self, format_options):
            captured["format_options"] = format_options

    api = {
        "PdfPipelineOptions": PipelineOptions,
        "TableStructureOptions": TableOptions,
        "TesseractCliOcrOptions": TesseractOptions,
        "OcrMode": OcrMode,
        "InputFormat": InputFormat,
        "PdfFormatOption": PdfFormatOption,
        "DocumentConverter": DocumentConverter,
    }
    adapter = skill.DoclingAdapter(image_scale=2.0)
    adapter._converter(api, full=True, force_full_page_ocr=True)
    options = captured["format_options"][InputFormat.PDF].pipeline_options
    assert options.do_ocr is True
    assert options.do_table_structure is True
    assert options.table_structure_options.do_cell_matching is True
    assert options.generate_page_images is True
    assert options.generate_picture_images is True
    assert options.images_scale == 2.0
    assert options.ocr_options.lang == ["auto"]
    assert options.ocr_options.mode == OcrMode.FULL_PAGE


def test_docling_text_coverage_gate_requests_full_page_ocr_for_scanned_document():
    class EmptyDocument:
        pages = {1: object(), 2: object()}

        @staticmethod
        def iterate_items():
            return iter([])

    assert skill.DoclingAdapter._needs_full_page_ocr(EmptyDocument()) is True
