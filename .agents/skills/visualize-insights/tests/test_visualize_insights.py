import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

# Mock google.antigravity to avoid protobuf import errors on the system
sys.modules['google.antigravity'] = MagicMock()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts")))
import visualize_insights

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
    def test_discover_full_transcripts_prefers_dash_and_supports_legacy_underscore(self, tmp_path):
        mapped_path = tmp_path / "mapped-transcript.md"
        mapped_path.write_text(SAMPLE_MAPPED_TRANSCRIPT, encoding="utf-8")
        preferred = tmp_path / "transcript-Anh-A.md"
        preferred.write_text("# Preferred", encoding="utf-8")
        legacy = tmp_path / "transcript_Chị-B.md"
        legacy.write_text("# Legacy", encoding="utf-8")

        matched = visualize_insights.discover_full_transcripts(
            mapped_path,
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
        mapped_path = tmp_path / "mapped-transcript.md"
        mapped_path.write_text(SAMPLE_MAPPED_TRANSCRIPT, encoding="utf-8")
        (tmp_path / "transcript-Anh-A.md").write_text(
            "# Interview A\n\n**[00:01] [speaker_0]** <br>\nXin chào A.",
            encoding="utf-8",
        )
        (tmp_path / "transcript-Chị-B.md").write_text(
            "# Interview B\n\n**[00:02] [speaker_1]** <br>\nXin chào B.",
            encoding="utf-8",
        )

        footer, drawer = visualize_insights.build_full_transcript_ui(
            ["Anh A", "Chị B"],
            mapped_path,
        )

        assert footer.count("Xem tất cả") == 2
        assert footer.count("openTranscriptDrawer") == 2
        assert 'colspan="4"' in footer
        assert "Bản ghi đầy đủ — Anh A" in drawer
        assert "Bản ghi đầy đủ — Chị B" in drawer
        assert "Xin chào A." in drawer
        assert "Xin chào B." in drawer
        assert 'id="full-transcript-drawer"' in drawer

    def test_build_full_transcript_ui_disables_missing_source(self, tmp_path):
        mapped_path = tmp_path / "mapped-transcript.md"
        mapped_path.write_text(SAMPLE_MAPPED_TRANSCRIPT, encoding="utf-8")

        footer, drawer = visualize_insights.build_full_transcript_ui(["Anh A"], mapped_path)

        assert "Xem tất cả" in footer
        assert 'disabled aria-disabled="true"' in footer
        assert "Không có tệp nguồn" in drawer

class TestDeterministicStats:
    @patch('visualize_insights.shutil.which', return_value=None)
    @patch('visualize_insights.glob.glob')
    def test_get_folder_stats(self, mock_glob, mock_which):
        import asyncio

        mock_glob.return_value = []
        stats = asyncio.run(visualize_insights.get_folder_stats('/path'))
        # Basic structure validation
        assert "total_interviewees" in stats
        assert "total_time_html" in stats
        assert "audio_names" in stats

    def test_extract_summary_insights(self):
        insights_md = "some text\n## Summary of Discovered Insights\n- **Tần suất**: Nội dung 1\n- Nội dung 2"
        html = visualize_insights.extract_summary_insights(insights_md)
        assert "<li><strong>Tần suất</strong>: Nội dung 1</li>" in html
        assert "<li>Nội dung 2</li>" in html

class TestChartData:
    def test_extract_chart_data_basic(self):
        labels, data, total = visualize_insights.extract_chart_data(SAMPLE_INSIGHTS)
        assert total == 2  # max of [2, 0]
        parsed_data = json.loads(data)
        assert parsed_data == [2, 0]

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
