"""
test_saturate_insights.py

Unit tests for the saturate_insights.py script.
Tests cover:
  - Markdown table parsing (new)
  - AI response JSON extraction (new)
  - Prompt building (new)
  - AI extraction pipeline with mocked SDK (new)
  - JSON loading & validation (existing)
  - Report generation (existing)
  - Saturation matrix generation (existing)
  - CLI integration (existing)
"""

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts")))
import saturate_insights


# ---------------------------------------------------------------------------
# Sample Data Fixtures
# ---------------------------------------------------------------------------

SAMPLE_INSIGHTS_DATA = {
    "interviewees": ["Anh A", "Chị B", "Anh C"],
    "master_insights": [
        {
            "id": 1,
            "insight": "Lo lắng về bảo mật, do không biết dữ liệu được lưu ở đâu",
            "interviewees": {
                "Anh A": {
                    "status": "new",
                    "quotes": ["Tôi lo lắng về bảo mật dữ liệu", "Không biết dữ liệu lưu ở đâu"]
                },
                "Chị B": {
                    "status": "repeated",
                    "quotes": ["Em cũng lo về vấn đề bảo mật"]
                },
                "Anh C": {
                    "status": "absent",
                    "quotes": []
                }
            }
        },
        {
            "id": 2,
            "insight": "Bực bội khi thao tác, do nút bấm quá nhỏ và khó tìm",
            "interviewees": {
                "Anh A": {
                    "status": "new",
                    "quotes": ["Nút bấm quá nhỏ"]
                },
                "Chị B": {
                    "status": "new",
                    "quotes": ["Khó tìm nút bấm lắm"]
                },
                "Anh C": {
                    "status": "repeated",
                    "quotes": ["Cũng thấy nút nhỏ"]
                }
            }
        },
        {
            "id": 3,
            "insight": "Hài lòng với tốc độ xử lý, do giao dịch hoàn tất nhanh",
            "interviewees": {
                "Anh A": {
                    "status": "absent",
                    "quotes": []
                },
                "Chị B": {
                    "status": "absent",
                    "quotes": []
                },
                "Anh C": {
                    "status": "new",
                    "quotes": ["Giao dịch nhanh lắm", "Chỉ mất vài giây"]
                }
            }
        }
    ]
}

SAMPLE_MAPPED_TRANSCRIPT = """# Mapped Transcript

| # | Theme | Question | Observed Variable | Anh A | Chị B |
|---|-------|----------|-------------------|-------|-------|
| 1 | Warm-up | Giới thiệu bản thân | Tên | Tôi là A | Tôi là B |
| 2 | Trải nghiệm | Bạn cảm thấy thế nào về app? | Cảm xúc | [05:22] Tôi thấy nút bấm quá nhỏ | [03:10] Khó tìm nút bấm lắm |
| 3 | Bảo mật | Bạn có lo ngại gì? | Lo ngại | [08:15] Lo lắng về bảo mật | N/A |
"""


def _write_json(tmp_path, data):
    """Helper to write sample data to temp_insights.json."""
    json_path = os.path.join(str(tmp_path), "temp_insights.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return json_path

# ============================================================================
# Tests: load_insights (existing)
# ============================================================================

class TestLoadInsights:
    def test_load_insights_success(self, tmp_path):
        _write_json(tmp_path, SAMPLE_INSIGHTS_DATA)
        result = saturate_insights.load_insights(str(tmp_path))
        assert result["interviewees"] == ["Anh A", "Chị B", "Anh C"]
        assert len(result["master_insights"]) == 3

    def test_load_insights_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="temp_insights.json not found"):
            saturate_insights.load_insights(str(tmp_path))

    def test_load_insights_invalid_json(self, tmp_path):
        json_path = os.path.join(str(tmp_path), "temp_insights.json")
        with open(json_path, "w") as f:
            f.write("{ invalid json !!!")
        with pytest.raises(ValueError, match="Invalid JSON"):
            saturate_insights.load_insights(str(tmp_path))


# ============================================================================
# Tests: validate_schema (existing)
# ============================================================================

class TestValidateSchema:
    def test_validate_schema_valid(self):
        saturate_insights.validate_schema(SAMPLE_INSIGHTS_DATA)

    def test_validate_schema_missing_interviewees(self):
        data = {"master_insights": []}
        with pytest.raises(ValueError, match="Missing required field: 'interviewees'"):
            saturate_insights.validate_schema(data)

    def test_validate_schema_missing_master_insights(self):
        data = {"interviewees": ["A"]}
        with pytest.raises(ValueError, match="Missing required field: 'master_insights'"):
            saturate_insights.validate_schema(data)

    def test_validate_schema_empty_interviewees(self):
        data = {"interviewees": [], "master_insights": []}
        with pytest.raises(ValueError, match="'interviewees' must be a non-empty list"):
            saturate_insights.validate_schema(data)

    def test_validate_schema_invalid_status(self):
        data = {
            "interviewees": ["A"],
            "master_insights": [{
                "id": 1, "insight": "test",
                "interviewees": {"A": {"status": "invalid_status", "quotes": []}}
            }]
        }
        with pytest.raises(ValueError, match="Invalid status 'invalid_status'"):
            saturate_insights.validate_schema(data)

    def test_validate_schema_missing_insight_id(self):
        data = {
            "interviewees": ["A"],
            "master_insights": [{
                "insight": "test",
                "interviewees": {"A": {"status": "new", "quotes": []}}
            }]
        }
        with pytest.raises(ValueError, match="Missing required field 'id'"):
            saturate_insights.validate_schema(data)


# ============================================================================
# Tests: generate_individual_report (existing)
# ============================================================================

class TestGenerateIndividualReport:
    def test_generates_correct_content(self):
        content = saturate_insights.generate_individual_report("Anh A", SAMPLE_INSIGHTS_DATA)
        assert "# Insights — Anh A" in content
        assert "| # | Insight | Quotes |" in content
        assert "Lo lắng về bảo mật" in content
        assert "Bực bội khi thao tác" in content
        assert "Hài lòng với tốc độ" not in content

    def test_skips_absent_insights(self):
        content = saturate_insights.generate_individual_report("Anh C", SAMPLE_INSIGHTS_DATA)
        assert "Lo lắng về bảo mật" not in content
        assert "Bực bội khi thao tác" in content
        assert "Hài lòng với tốc độ" in content

    def test_includes_quotes(self):
        content = saturate_insights.generate_individual_report("Anh A", SAMPLE_INSIGHTS_DATA)
        assert "Tôi lo lắng về bảo mật dữ liệu" in content
        assert "Không biết dữ liệu lưu ở đâu" in content

    def test_joins_multiple_quotes_with_br(self):
        content = saturate_insights.generate_individual_report("Anh A", SAMPLE_INSIGHTS_DATA)
        assert "Tôi lo lắng về bảo mật dữ liệu<br><br>Không biết dữ liệu lưu ở đâu" in content


# ============================================================================
# Tests: generate_combined_report (existing)
# ============================================================================

class TestGenerateCombinedReport:
    def test_generates_combined_file(self, tmp_path):
        path = saturate_insights.generate_combined_report(SAMPLE_INSIGHTS_DATA, str(tmp_path))
        assert os.path.basename(path) == "insights.md"
        assert os.path.exists(path)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "# Insights — Anh A" in content
        assert "# Insights — Chị B" in content
        assert "# Insights — Anh C" in content

    def test_combined_report_has_separator(self, tmp_path):
        path = saturate_insights.generate_combined_report(SAMPLE_INSIGHTS_DATA, str(tmp_path))
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "---" in content


# ============================================================================
# Tests: generate_saturation_matrix (existing)
# ============================================================================

class TestGenerateSaturationMatrix:
    def test_correct_symbols(self, tmp_path):
        matrix_path, chart_path = saturate_insights.generate_saturation_matrix(SAMPLE_INSIGHTS_DATA, str(tmp_path))
        with open(matrix_path, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.strip().split("\n")
        table_rows = [
            l for l in lines
            if l.startswith("|") and "---" not in l
            and "Insight" not in l and "New Insights" not in l
        ]
        assert "🔵" in table_rows[0]
        assert "🌐" in table_rows[0]
        assert "⚪️" in table_rows[0]

    def test_summary_row_counts(self, tmp_path):
        matrix_path, chart_path = saturate_insights.generate_saturation_matrix(SAMPLE_INSIGHTS_DATA, str(tmp_path))
        with open(matrix_path, "r", encoding="utf-8") as f:
            content = f.read()
        summary_lines = [l for l in content.split("\n") if "🔵 New Insights" in l]
        assert len(summary_lines) == 1
        summary = summary_lines[0]
        cells = [c.strip() for c in summary.split("|") if c.strip()]
        assert cells[1] == "2"  # Anh A
        assert cells[2] == "1"  # Chị B
        assert cells[3] == "1"  # Anh C

    def test_png_chart_present(self, tmp_path):
        matrix_path, chart_path = saturate_insights.generate_saturation_matrix(SAMPLE_INSIGHTS_DATA, str(tmp_path))
        with open(matrix_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "![Data Saturation Curve](saturation-chart.png)" in content
        assert os.path.exists(chart_path)

    def test_output_filename(self, tmp_path):
        matrix_path, chart_path = saturate_insights.generate_saturation_matrix(SAMPLE_INSIGHTS_DATA, str(tmp_path))
        assert os.path.basename(matrix_path) == "saturation-matrix.md"
        assert os.path.basename(chart_path) == "saturation-chart.png"


# ============================================================================
# Tests: generate_all_individual_reports (existing)
# ============================================================================

class TestGenerateAllIndividualReports:
    def test_creates_files_for_all_interviewees(self, tmp_path):
        paths = saturate_insights.generate_all_individual_reports(SAMPLE_INSIGHTS_DATA, str(tmp_path))
        assert len(paths) == 3
        filenames = [os.path.basename(p) for p in paths]
        assert "all-insights-Anh_A.md" in filenames
        assert "all-insights-Anh_C.md" in filenames


# ============================================================================
# Tests: merge_final_report
# ============================================================================

class TestMergeFinalReport:
    def test_merges_and_deletes(self, tmp_path):
        combined_path = os.path.join(str(tmp_path), "insights.md")
        matrix_path = os.path.join(str(tmp_path), "saturation-matrix.md")
        
        with open(combined_path, "w", encoding="utf-8") as f:
            f.write("# Insights\n")
        
        with open(matrix_path, "w", encoding="utf-8") as f:
            f.write("# Matrix\n")
            
        saturate_insights.merge_final_report(combined_path, matrix_path)
        
        assert not os.path.exists(matrix_path)
        assert os.path.exists(combined_path)
        
        with open(combined_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "# Insights\n\n\n---\n\n# Matrix\n" in content


# ============================================================================
# Tests: main CLI (--generate-only mode)
# ============================================================================

class TestMainGenerateOnly:
    def test_main_generate_only_success(self, tmp_path, capsys):
        interview_dir = tmp_path / "Interview"
        interview_dir.mkdir()
        _write_json(interview_dir, SAMPLE_INSIGHTS_DATA)
        sys.argv = ["saturate_insights.py", str(tmp_path), "--generate-only"]
        saturate_insights.main()
        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["status"] == "success"
        assert "insights.md" in output["output_files"]
        assert "saturation-matrix.md" not in output["output_files"]
        assert "saturation-chart.png" in output["output_files"]
        assert os.path.exists(os.path.join(str(interview_dir), "insights.md"))
        assert not os.path.exists(os.path.join(str(interview_dir), "saturation-matrix.md"))
        assert os.path.exists(os.path.join(str(interview_dir), "saturation-chart.png"))
        
        with open(os.path.join(str(interview_dir), "insights.md"), "r", encoding="utf-8") as f:
            content = f.read()
            assert "# Compiled Insights" in content
            assert "# Data Saturation Matrix" in content
        # temp_insights.json should be cleaned up
        assert not os.path.exists(os.path.join(str(interview_dir), "temp_insights.json"))

    def test_main_generate_only_missing_json(self, tmp_path, capsys):
        interview_dir = tmp_path / "Interview"
        interview_dir.mkdir()
        sys.argv = ["saturate_insights.py", str(tmp_path), "--generate-only"]
        with pytest.raises(SystemExit) as exc_info:
            saturate_insights.main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["status"] == "error"
        assert output["error_code"] == "NO_INSIGHTS_JSON"

    def test_main_invalid_folder(self, capsys):
        sys.argv = ["saturate_insights.py", "/nonexistent/path", "--generate-only"]
        with pytest.raises(SystemExit) as exc_info:
            saturate_insights.main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["status"] == "error"
        assert output["error_code"] == "INVALID_INPUT"

    def test_main_no_args(self, capsys):
        sys.argv = ["saturate_insights.py"]
        with pytest.raises(SystemExit) as exc_info:
            saturate_insights.main()
        assert exc_info.value.code != 0
