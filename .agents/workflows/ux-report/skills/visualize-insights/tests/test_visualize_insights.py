import os
import sys
import json
import pytest
import asyncio
import subprocess
import time
import tracemalloc
from unittest.mock import patch, MagicMock

# Mock google.antigravity to avoid protobuf import errors on the system
sys.modules['google.antigravity'] = MagicMock()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts")))
import visualize_insights

SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../scripts/visualize_insights.py")
)

SAMPLE_MAPPED_TRANSCRIPT = """# Mapped Transcript

| # | Theme | Question | Observed Variable | Anh A | Chị B |
|---|-------|----------|-------------------|-------|-------|
| 1 | Warm-up | Giới thiệu bản thân | Tên | Tôi là A | Tôi là B |
| 2 | Trải nghiệm | Bạn cảm thấy thế nào về app? | Cảm xúc | [05:22] Tôi thấy nút bấm quá nhỏ | [03:10] Khó tìm nút bấm lắm |
| 3 | Bảo mật | Bạn có lo ngại gì? | Lo ngại | [08:15] Lo lắng về bảo mật | N/A |
"""

SAMPLE_INSIGHTS = """# Compiled Insights

# Insights — Anh A
| # | Insight | Quotes |
|---|---|---|
| 1 | Lo lắng về bảo mật, do không biết dữ liệu được lưu ở đâu | Tôi lo lắng về bảo mật dữ liệu |
| 2 | Bực bội khi thao tác, do nút bấm quá nhỏ và khó tìm | Nút bấm quá nhỏ |

# Insights — Chị B
| # | Insight | Quotes |
|---|---|---|
| 1 | Lo lắng về bảo mật, do không biết dữ liệu được lưu ở đâu | Tôi cũng lo về bảo mật |

---
# Data Saturation Matrix
| Insight | Anh A | Chị B |
|---------|-------|-------|
| Lo lắng về bảo mật, do không biết dữ liệu được lưu ở đâu | 🔵 | 🌐 |
| Bực bội khi thao tác, do nút bấm quá nhỏ và khó tìm | 🔵 | ⚪️ |
| **🔵 New Insights** | 2 | 0 |

## Data Saturation Chart

## Summary of Discovered Insights
- **Bảo mật**: Người dùng lo lắng về vấn đề bảo mật dữ liệu
- **UX**: Nút bấm quá nhỏ gây khó chịu
"""

SAMPLE_INSIGHTS_SINGLE_USER = """# Compiled Insights

# Insights — Chị Dung
| # | Insight | Quotes |
|---|---------|--------|
| 1 | Xử lý 10-15 bộ hồ sơ mỗi tháng | Trung bình khoảng mười lăm bộ |
| 2 | Khách hàng phải chuẩn bị hồ sơ trước | Tư vấn trước, chuẩn bị thông tin |

---
# Data Saturation Matrix
| Insight | Chị Dung |
| --- | --- |
| Xử lý 10-15 bộ hồ sơ mỗi tháng | 🔵 |
| Khách hàng phải chuẩn bị hồ sơ trước | 🔵 |
| **🔵 New Insights** | 2 |

## Summary of Discovered Insights
- Nghiệp vụ chuyển tiền quốc tế tại quầy không phát sinh thường xuyên.
"""

SAMPLE_JOURNEY = """# Customer Journey Map

| Dimension | Stage 1 | Stage 2 | Stage 3 | Stage 4 | Stage 5 |
|---|---|---|---|---|---|
| **Stage goal** | Learn | Compare | Decide | Use | Recommend |
| **Stage Emotion (1-5)** | 3 - Neutral 😐 | 4 - Positive 🙂 | 3 - Neutral 😐 | 2 - Slightly Negative 🙁 | 5 - Very Positive 😄 |
"""


def build_valid_payload(tmp_path, insights=SAMPLE_INSIGHTS, transcript=SAMPLE_MAPPED_TRANSCRIPT):
    input_dir = tmp_path / "inputs"
    output_dir = tmp_path / "output"
    input_dir.mkdir(parents=True)
    insights_path = input_dir / "insights.md"
    mapped_path = input_dir / "mapped-transcript.md"
    journey_path = input_dir / "journey-map.md"
    transcript_a = input_dir / "transcript-Anh-A.md"
    transcript_b = input_dir / "transcript-Chị-B.md"
    insights_path.write_text(insights, encoding="utf-8")
    mapped_path.write_text(transcript, encoding="utf-8")
    journey_path.write_text(SAMPLE_JOURNEY, encoding="utf-8")
    transcript_a.write_text("# Anh A\n\n**[00:01] [speaker_0]** <br>\nXin chào A.", encoding="utf-8")
    transcript_b.write_text("# Chị B\n\n**[00:02] [speaker_1]** <br>\nXin chào B.", encoding="utf-8")
    return {
        "insights_path": str(insights_path),
        "transcript_path": str(mapped_path),
        "full_transcript_paths": [str(transcript_a), str(transcript_b)],
        "journey_path": str(journey_path),
        "media_paths": [],
        "output_dir": str(output_dir),
        "project_name": "Research Report",
        "open_browser": False,
    }

class TestDataParsing:
    def test_parse_transcript_to_html(self):
        rows, thead = visualize_insights.parse_transcript_to_html(SAMPLE_MAPPED_TRANSCRIPT)
        assert "Warm-up" in rows
        assert "Giới thiệu bản thân" in rows
        assert "Khó tìm nút bấm lắm" in rows
        assert "Lo lắng về bảo mật" in rows
        # N/A should be omitted
        assert "N/A" not in rows
        # Count rows (3 data rows)
        assert rows.count("<tr") == 3
        # Headers should contain user names
        assert "Anh A" in thead
        assert "Chị B" in thead

    def test_parse_insights_to_html(self):
        rows, thead, headers = visualize_insights.parse_insights_to_html(SAMPLE_INSIGHTS)
        # Should parse from Data Saturation Matrix section
        assert "Lo lắng về bảo mật, do không biết dữ liệu được lưu ở đâu" in rows
        assert "Bực bội khi thao tác, do nút bấm quá nhỏ và khó tìm" in rows
        # Should display saturation markers
        assert "🔵" in rows
        assert "🌐" in rows
        # Should have quote toggle buttons linked to per-interviewee quotes
        assert "toggleQuote" in rows
        assert "Tôi lo lắng về bảo mật dữ liệu" in rows  # Quote from Anh A
        # Should NOT contain the matrix summary row
        assert "New Insights" not in rows
        # Headers should be user names from matrix, not "Quotes"
        assert headers == ["Anh A", "Chị B"]
        assert "Anh A" in thead
        assert "Chị B" in thead
        # Count rows (2 insights)
        assert rows.count("<tr") == 2

    def test_parse_insights_single_user(self):
        """Test with a single interviewee — headers should show user name, not 'Quotes'."""
        rows, thead, headers = visualize_insights.parse_insights_to_html(SAMPLE_INSIGHTS_SINGLE_USER)
        assert headers == ["Chị Dung"]
        assert "Chị Dung" in thead
        assert "Quotes" not in thead
        assert rows.count("<tr") == 2
        assert "🔵" in rows
        # Quotes should be linked
        assert "Trung bình khoảng mười lăm bộ" in rows

    def test_parse_interviewee_quotes(self):
        quotes = visualize_insights.parse_interviewee_quotes(SAMPLE_INSIGHTS)
        assert len(quotes) == 2
        # Check Anh A's quotes
        insight1 = "Lo lắng về bảo mật, do không biết dữ liệu được lưu ở đâu"
        assert insight1 in quotes
        assert "Anh A" in quotes[insight1]
        assert quotes[insight1]["Anh A"] == "Tôi lo lắng về bảo mật dữ liệu"
        # Check Chị B's quote for same insight
        assert "Chị B" in quotes[insight1]
        assert quotes[insight1]["Chị B"] == "Tôi cũng lo về bảo mật"
        # Check Anh A's second insight
        insight2 = "Bực bội khi thao tác, do nút bấm quá nhỏ và khó tìm"
        assert insight2 in quotes
        assert quotes[insight2]["Anh A"] == "Nút bấm quá nhỏ"
        # Chị B should not have this insight
        assert "Chị B" not in quotes[insight2]

    def test_parse_interviewee_quotes_single_user(self):
        quotes = visualize_insights.parse_interviewee_quotes(SAMPLE_INSIGHTS_SINGLE_USER)
        assert len(quotes) == 2
        assert "Chị Dung" in quotes["Xử lý 10-15 bộ hồ sơ mỗi tháng"]

    def test_parse_transcript_case_insensitive_and_topic(self):
        topic_transcript = """# Topic Transcript
| # | Topic | Question | Observed Variable | User X |
|---|-------|----------|-------------------|--------|
| 1 | Phase 1 | Cảm xúc? | Navigation | Good |
"""
        rows, thead = visualize_insights.parse_transcript_to_html(topic_transcript)
        assert "Phase 1" in rows
        assert "User X" in thead

    def test_extract_transcript_headers_with_audio_name_override(self):
        headers = visualize_insights.extract_transcript_headers(
            SAMPLE_MAPPED_TRANSCRIPT,
            audio_names=["Audio A", "Audio B"],
        )
        assert headers == ["Audio A", "Audio B"]


class TestFullTranscriptDrawer:
    def test_match_full_transcript_inputs_requires_non_empty_list(self):
        with pytest.raises(ValueError, match="must be a non-empty list"):
            visualize_insights.match_full_transcript_inputs([], ["Anh A"])

    def test_match_full_transcript_inputs_covers_every_interviewee(self, tmp_path):
        preferred = tmp_path / "transcript-Anh-A.md"
        preferred.write_text("# Preferred", encoding="utf-8")
        legacy = tmp_path / "transcript_Chị-B.md"
        legacy.write_text("# Legacy", encoding="utf-8")

        matched = visualize_insights.match_full_transcript_inputs(
            [str(preferred), str(legacy)],
            ["Anh A", "Chị B"],
        )

        assert matched["Anh A"] == preferred
        assert matched["Chị B"] == legacy

    def test_render_full_transcript_markdown_is_safe_and_readable(self):
        transcript_md = """# Interview

**[00:01] [speaker_0]** <br>
Xin chào <script>alert('x')</script>
"""
        rendered = visualize_insights.render_full_transcript_markdown(transcript_md)

        assert "<h2" in rendered
        assert "text-blue-700" in rendered
        assert "<strong>[00:01] [speaker_0]</strong>" in rendered
        assert "&lt;script&gt;alert('x')&lt;/script&gt;" in rendered
        assert "<script>" not in rendered

    def test_build_full_transcript_ui_adds_one_action_per_interviewee(self, tmp_path):
        transcript_a = tmp_path / "transcript-Anh-A.md"
        transcript_a.write_text(
            "# Interview A\n\n**[00:01] [speaker_0]** <br>\nXin chào A.",
            encoding="utf-8",
        )
        transcript_b = tmp_path / "transcript-Chị-B.md"
        transcript_b.write_text(
            "# Interview B\n\n**[00:02] [speaker_1]** <br>\nXin chào B.",
            encoding="utf-8",
        )

        transcript_files = visualize_insights.match_full_transcript_inputs(
            [str(transcript_a), str(transcript_b)],
            ["Anh A", "Chị B"],
        )
        footer, drawer = visualize_insights.build_full_transcript_ui(
            ["Anh A", "Chị B"],
            transcript_files,
        )

        assert footer.count("Xem tất cả") == 2
        assert footer.count("openTranscriptDrawer") == 2
        assert 'colspan="4"' in footer
        assert "Bản ghi đầy đủ — Anh A" in drawer
        assert "Bản ghi đầy đủ — Chị B" in drawer
        assert 'type="application/json"' in drawer
        assert drawer.count('data-full-transcript-payload') == 2
        assert drawer.count('data-full-transcript-document') == 2
        assert 'id="full-transcript-drawer"' in drawer
        assert drawer.count('placeholder="Search in full transcript..."') == 2
        assert drawer.count('oninput="searchFullTranscript') == 2
        assert 'id="full-transcript-search-0"' in drawer
        assert 'id="full-transcript-search-1"' in drawer
        assert drawer.count('data-full-transcript-document') == 2

    def test_base_template_supports_scoped_full_transcript_search(self):
        template_path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "../template/insights-template.html",
            )
        )
        with open(template_path, "r", encoding="utf-8") as template_file:
            template = template_file.read()

        assert "function searchFullTranscript(input, panelId)" in template
        assert "function clearFullTranscriptSearch(inputId, panelId)" in template
        assert "data-full-transcript-match" in template
        assert "NodeFilter.SHOW_TEXT" in template
        assert "function hydrateFullTranscript(panel)" in template
        assert "hydrateFullTranscript(panel);" in template

    def test_match_full_transcript_inputs_rejects_missing_interviewee(self, tmp_path):
        only_transcript = tmp_path / "transcript-Anh-A.md"
        only_transcript.write_text("# Interview A", encoding="utf-8")

        with pytest.raises(ValueError, match="Missing full transcript input for: Chị B"):
            visualize_insights.match_full_transcript_inputs(
                [str(only_transcript)],
                ["Anh A", "Chị B"],
            )

    def test_match_full_transcript_inputs_rejects_invalid_filename(self, tmp_path):
        invalid_transcript = tmp_path / "interview-Anh-A.md"
        invalid_transcript.write_text("# Interview A", encoding="utf-8")

        with pytest.raises(ValueError, match=r"must match transcript-\*\.md"):
            visualize_insights.match_full_transcript_inputs(
                [str(invalid_transcript)],
                ["Anh A"],
            )


class TestDeterministicStats:
    @patch('visualize_insights.shutil.which', return_value=None)
    def test_get_media_stats(self, mock_which):
        stats = asyncio.run(visualize_insights.get_media_stats([]))
        # Basic structure validation
        assert "total_time_html" in stats
        assert stats["media_count"] == 0

    def test_extract_summary_insights(self):
        insights_md = "some text\n## Summary of Discovered Insights\n- **Tần suất**: Nội dung 1\n- Nội dung 2"
        html = visualize_insights.extract_summary_insights(insights_md)
        assert "<li><strong>Tần suất</strong>: Nội dung 1</li>" in html
        assert "<li>Nội dung 2</li>" in html

class TestChartData:
    def test_extract_chart_data_basic(self):
        labels, data, total = visualize_insights.extract_chart_data(SAMPLE_INSIGHTS)
        assert total == 2
        parsed_data = json.loads(data)
        assert parsed_data == [2, 2]

    def test_extract_chart_data_uses_matrix_headers(self):
        """Without audio_names, chart should use saturation matrix header names."""
        labels, data, total = visualize_insights.extract_chart_data(SAMPLE_INSIGHTS)
        parsed_labels = json.loads(labels)
        assert parsed_labels == ["Anh A", "Chị B"]

    def test_extract_chart_data_with_audio_names(self):
        labels, data, total = visualize_insights.extract_chart_data(SAMPLE_INSIGHTS, audio_names=["Nguyen A", "Tran B"])
        parsed_labels = json.loads(labels)
        assert parsed_labels == ["Nguyen A", "Tran B"]

    def test_extract_chart_data_single_user(self):
        labels, data, total = visualize_insights.extract_chart_data(SAMPLE_INSIGHTS_SINGLE_USER)
        parsed_labels = json.loads(labels)
        assert parsed_labels == ["Chị Dung"]
        assert total == 2

class TestE2E:
    @patch('sys.stdin.isatty', return_value=True)
    def test_main_missing_args(self, mock_isatty, capsys):
        sys.argv = ["visualize_insights.py"]
        with pytest.raises(SystemExit):
            import asyncio
            asyncio.run(visualize_insights.main())
        out, _ = capsys.readouterr()
        assert "Missing input JSON from arguments, file, or stdin" in out

    def test_main_success_path_returns_absolute_artifacts(self, tmp_path):
        payload = build_valid_payload(tmp_path)

        completed = subprocess.run(
            [sys.executable, SCRIPT_PATH, json.dumps(payload, ensure_ascii=False)],
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 0, completed.stdout + completed.stderr
        result = json.loads(completed.stdout)
        assert result["status"] == "success"
        assert os.path.isabs(result["output_file"])
        assert os.path.isabs(result["manifest_file"])

    def test_main_invalid_json_returns_stable_code(self):
        completed = subprocess.run(
            [sys.executable, SCRIPT_PATH, "{not-json"],
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 1
        assert json.loads(completed.stdout)["code"] == "INVALID_JSON"

class TestJourneyMap:
    def test_parse_journey_map_emotion_styling(self):
        journey_md = """# Journey Map
| Dimension | Stage 1 | Stage 2 | Stage 3 | Stage 4 | Stage 5 |
|---|---|---|---|---|---|
| **Stage Emotion (1-5)** | 5 - Hào hứng | 4 - Thích thú | 3 - Bình thường | 2 - Hơi lo lắng | 1 - Thất vọng |
"""
        rows = visualize_insights.parse_journey_map(journey_md)
        # Check for premium border classes and shadow glow highlights, avoiding direct bg-emerald-50 overrides
        assert "bg-white border-emerald-500" in rows
        assert "shadow-[0_0_8px_rgba(16,185,129,0.15)]" in rows
        assert "bg-white border-blue-500" in rows
        assert "shadow-[0_0_8px_rgba(59,130,246,0.15)]" in rows
        assert "bg-white border-rose-500" in rows
        assert "shadow-[0_0_8px_rgba(239,68,68,0.15)]" in rows

    def test_parse_journey_map_markdown_bolding(self):
        journey_md = """# Journey Map
| Dimension | Stage 1 | Stage 2 | Stage 3 | Stage 4 | Stage 5 |
|---|---|---|---|---|---|
| **Metrics** | **Metrics:** rate 1 | **Metrics:** rate 2 | **Metrics:** rate 3 | **Metrics:** rate 4 | **Metrics:** rate 5 |
"""
        rows = visualize_insights.parse_journey_map(journey_md)
        assert "<strong>Metrics:</strong>" in rows


class TestSecurityAndAccuracy:
    def test_inline_markdown_escapes_html_and_blocks_unsafe_links(self):
        rendered = visualize_insights.render_inline_markdown(
            "<script>alert(1)</script> [safe](https://example.com) [bad](javascript:alert(1))"
        )

        assert "<script>" not in rendered
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
        assert 'href="https://example.com"' in rendered
        assert "javascript:" not in rendered
        assert 'rel="noopener noreferrer"' in rendered

    def test_inline_markdown_preserves_only_canonical_highlight_markup(self):
        rendered = visualize_insights.render_inline_markdown(
            '[00:03] **<mark style="background-color: yellow;">Safe quote</mark>**<br>'
            '<mark onclick="alert(1)">Unsafe wrapper</mark>'
        )

        assert '<mark class="bg-yellow-200' in rendered
        assert "<strong><mark" in rendered
        assert "<br>" in rendered
        assert "onclick" in rendered
        assert "&lt;mark onclick=" in rendered
        assert "&lt;/mark&gt;" in rendered

    def test_chart_data_is_cumulative_and_total_is_final_value(self):
        insights = SAMPLE_INSIGHTS.replace(
            "| **🔵 New Insights** | 2 | 0 |",
            "| **🔵 New Insights** | 2 | 1 |",
        )

        labels, data, total = visualize_insights.extract_chart_data(insights)

        assert json.loads(labels) == ["Anh A", "Chị B"]
        assert json.loads(data) == [2, 3]
        assert total == 3

    def test_full_transcript_payload_cannot_close_script_element(self, tmp_path):
        transcript = tmp_path / "transcript-Anh-A.md"
        transcript.write_text("</script><script>alert(1)</script>", encoding="utf-8")

        _, drawer = visualize_insights.build_full_transcript_ui(
            ["Anh A"], {"Anh A": transcript}
        )

        assert "</script><script>" not in drawer
        assert "\\u0026lt;/script\\u0026gt;" in drawer
        assert 'data-full-transcript-document aria-live="polite"></div>' in drawer


class TestReportGeneration:
    def test_success_path_generates_atomic_html_and_manifest(self, tmp_path):
        payload = build_valid_payload(tmp_path)

        result = asyncio.run(visualize_insights.generate_report(payload))

        assert result["status"] == "success"
        output_file = os.path.abspath(result["output_file"])
        manifest_file = os.path.abspath(result["manifest_file"])
        assert output_file == result["output_file"]
        assert manifest_file == result["manifest_file"]
        html_content = open(output_file, encoding="utf-8").read()
        manifest = json.loads(open(manifest_file, encoding="utf-8").read())
        assert "{{" not in html_content
        assert "Soon" not in html_content
        assert html_content.index("Insights") < html_content.index("Persona") < html_content.index("Journey Map")
        assert 'role="tablist"' in html_content
        assert "function hydrateFullTranscript(panel)" in html_content
        assert "data-full-transcript-payload" in html_content
        assert "[2, 2]" in html_content
        assert manifest["status"] == "success"
        assert manifest["input_signature"] == result["input_signature"]
        assert manifest["output"]["path"] == output_file

    def test_unchanged_inputs_are_skipped_and_changed_inputs_rebuild(self, tmp_path):
        payload = build_valid_payload(tmp_path)
        first = asyncio.run(visualize_insights.generate_report(payload))
        output_path = os.path.abspath(first["output_file"])
        first_mtime = os.stat(output_path).st_mtime_ns

        second = asyncio.run(visualize_insights.generate_report(payload))
        assert second["status"] == "skipped"
        assert os.stat(output_path).st_mtime_ns == first_mtime

        insights_path = payload["insights_path"]
        with open(insights_path, "a", encoding="utf-8") as insights_file:
            insights_file.write("\n")
        third = asyncio.run(visualize_insights.generate_report(payload))
        assert third["status"] == "success"
        assert third["input_signature"] != first["input_signature"]

    def test_browser_open_is_opt_in_and_failure_is_a_warning(self, tmp_path):
        payload = build_valid_payload(tmp_path)
        payload["open_browser"] = True

        with patch("visualize_insights.webbrowser.open", return_value=False) as browser_open:
            result = asyncio.run(visualize_insights.generate_report(payload))

        browser_open.assert_called_once()
        assert result["status"] == "success"
        assert result["warnings"][0]["code"] == "BROWSER_OPEN_ERROR"

    def test_project_name_is_required_and_cannot_escape_output_dir(self, tmp_path):
        payload = build_valid_payload(tmp_path)
        payload.pop("project_name")
        with pytest.raises(visualize_insights.SkillError) as missing:
            asyncio.run(visualize_insights.generate_report(payload))
        assert missing.value.code == "INVALID_INPUT"

        payload["project_name"] = "../outside"
        with pytest.raises(visualize_insights.SkillError) as unsafe:
            asyncio.run(visualize_insights.generate_report(payload))
        assert unsafe.value.code == "OUTPUT_PATH_INVALID"

    def test_project_and_markdown_content_are_html_escaped(self, tmp_path):
        transcript = SAMPLE_MAPPED_TRANSCRIPT.replace("Warm-up", "<img src=x onerror=alert(1)>")
        payload = build_valid_payload(tmp_path, transcript=transcript)
        payload["project_name"] = "Research <img onerror=alert(1)>"

        result = asyncio.run(visualize_insights.generate_report(payload))
        html_content = open(result["output_file"], encoding="utf-8").read()

        assert "<img src=x onerror=alert(1)>" not in html_content
        assert "&lt;img src=x onerror=alert(1)&gt;" in html_content
        assert "<h1 class=\"text-xl font-bold text-blue-600 tracking-tight\">Research <img" not in html_content
        assert "Research &lt;img onerror=alert(1)&gt;" in html_content

    def test_empty_parse_results_and_invalid_journey_fail_with_stable_codes(self, tmp_path):
        payload = build_valid_payload(tmp_path)
        with open(payload["insights_path"], "w", encoding="utf-8") as insights_file:
            insights_file.write("# Empty insights\n")
        with pytest.raises(visualize_insights.SkillError) as parsing:
            asyncio.run(visualize_insights.generate_report(payload))
        assert parsing.value.code == "PARSING_ERROR"

        payload = build_valid_payload(tmp_path / "journey")
        with open(payload["journey_path"], "w", encoding="utf-8") as journey_file:
            journey_file.write("# Empty journey\n")
        with pytest.raises(visualize_insights.SkillError) as journey:
            asyncio.run(visualize_insights.generate_report(payload))
        assert journey.value.code == "JOURNEY_ERROR"

    def test_input_budget_rejects_oversized_payload(self, tmp_path):
        payload = build_valid_payload(tmp_path)
        payload["max_input_bytes"] = 10

        with pytest.raises(visualize_insights.SkillError) as oversized:
            asyncio.run(visualize_insights.generate_report(payload))

        assert oversized.value.code == "INPUT_TOO_LARGE"

    def test_unresolved_placeholders_fail_before_output_write(self, tmp_path):
        payload = build_valid_payload(tmp_path)
        templates, paths = visualize_insights._load_templates()
        templates["base"] += "{{ unresolved_value }}"

        with patch("visualize_insights._load_templates", return_value=(templates, paths)):
            with pytest.raises(visualize_insights.SkillError) as unresolved:
                asyncio.run(visualize_insights.generate_report(payload))

        assert unresolved.value.code == "TEMPLATE_ERROR"
        assert not os.path.exists(os.path.join(payload["output_dir"], "Research Report.html"))

    def test_atomic_write_preserves_last_good_output_on_replace_failure(self, tmp_path):
        payload = build_valid_payload(tmp_path)
        result = asyncio.run(visualize_insights.generate_report(payload))
        with open(result["output_file"], encoding="utf-8") as output:
            last_good = output.read()
        with open(payload["insights_path"], "a", encoding="utf-8") as insights_file:
            insights_file.write("\n")

        with patch("visualize_insights.os.replace", side_effect=OSError("replace failed")):
            with pytest.raises(visualize_insights.SkillError) as write_error:
                asyncio.run(visualize_insights.generate_report(payload))

        assert write_error.value.code == "OUTPUT_WRITE_ERROR"
        with open(result["output_file"], encoding="utf-8") as output:
            assert output.read() == last_good
        assert not list((tmp_path / "output").glob(".*.tmp"))

    def test_standalone_report_keeps_journey_section_with_empty_state(self, tmp_path):
        payload = build_valid_payload(tmp_path)
        payload.pop("journey_path")

        result = asyncio.run(visualize_insights.generate_report(payload))
        html_content = open(result["output_file"], encoding="utf-8").read()

        assert 'id="journey"' in html_content
        assert "No journey map was supplied" in html_content


def build_twenty_user_payload(tmp_path):
    users = [f"User {index:02d}" for index in range(1, 21)]
    mapped_header = "| # | Theme | Question | Observed Variable | " + " | ".join(users) + " |"
    mapped_separator = "|---|---|---|---|" + "---|" * len(users)
    mapped_row = "| 1 | Product | What works? | Value | " + " | ".join("Works well" for _ in users) + " |"
    mapped = "\n".join(["# Mapped Transcript", "", mapped_header, mapped_separator, mapped_row])
    sections = []
    for user in users:
        sections.append(
            f"# Insights — {user}\n| # | Insight | Quotes |\n|---|---|---|\n"
            f"| 1 | The workflow works reliably | Quote from {user} |"
        )
    matrix_header = "| Insight | " + " | ".join(users) + " |"
    matrix_separator = "|---|" + "---|" * len(users)
    matrix_row = "| The workflow works reliably | " + " | ".join("🔵" for _ in users) + " |"
    counts_row = "| **🔵 New Insights** | " + " | ".join(["1", *(["0"] * 19)]) + " |"
    insights = "\n\n".join(sections) + "\n\n# Data Saturation Matrix\n" + "\n".join(
        [matrix_header, matrix_separator, matrix_row, counts_row, "", "## Data Saturation Chart", "", "## Summary of Discovered Insights", "- The workflow works reliably"]
    )
    input_dir = tmp_path / "inputs"
    output_dir = tmp_path / "output"
    input_dir.mkdir(parents=True)
    insights_path = input_dir / "insights.md"
    mapped_path = input_dir / "mapped-transcript.md"
    insights_path.write_text(insights, encoding="utf-8")
    mapped_path.write_text(mapped, encoding="utf-8")
    full_transcripts = []
    for user in users:
        transcript = input_dir / f"transcript-{user.replace(' ', '-')}.md"
        transcript.write_text(f"# {user}\n\nThe workflow works reliably.", encoding="utf-8")
        full_transcripts.append(str(transcript))
    return {
        "insights_path": str(insights_path),
        "transcript_path": str(mapped_path),
        "full_transcript_paths": full_transcripts,
        "output_dir": str(output_dir),
        "project_name": "Twenty User Study",
        "media_paths": [],
        "open_browser": False,
    }


class TestScaling:
    def test_twenty_user_report_stays_bounded_and_warns(self, tmp_path):
        payload = build_twenty_user_payload(tmp_path)
        tracemalloc.start()
        started = time.perf_counter()

        result = asyncio.run(visualize_insights.generate_report(payload))

        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert result["status"] == "success"
        assert elapsed < 10
        assert peak < 128 * 1024 * 1024
        assert any(warning["code"] == "LARGE_STUDY_WARNING" for warning in result["warnings"])
        html_content = open(result["output_file"], encoding="utf-8").read()
        assert html_content.count("Xem tất cả") == 20
        assert html_content.count(
            '<script type="application/json" data-full-transcript-payload>'
        ) == 20
