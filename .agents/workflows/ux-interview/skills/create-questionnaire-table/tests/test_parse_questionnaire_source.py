import json
import os
import sys
import tempfile
import pytest
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../scripts"))

from parse_questionnaire_source import (
    find_target_sheet_name,
    normalize_dataframe,
    generate_markdown,
    parse_and_save,
    extract_google_sheet_id
)
from validate_questionnaire import validate_questionnaire


def test_extract_google_sheet_id():
    url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0"
    sheet_id = extract_google_sheet_id(url)
    assert sheet_id == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"


def test_find_target_sheet_name():
    sheet_names = ["1. Introduction", "2. Questionnaire", "3. Raw Data"]
    assert find_target_sheet_name(sheet_names) == "2. Questionnaire"

    variant_names = ["Overview", "2.Questionnaire", "Notes"]
    assert find_target_sheet_name(variant_names) == "2.Questionnaire"


def test_normalize_dataframe():
    data = [
        ["STT", "Chủ đề", "Câu hỏi", "Biến quan sát"],
        [1, "Warm Up", "Please introduce yourself", "Name"],
        [1, "Warm Up", "Please introduce yourself", "Age"],
        [2, "Product Experience", "What do you think about X", "Usability"]
    ]
    df = pd.DataFrame(data)
    rows = normalize_dataframe(df)

    assert len(rows) == 3
    assert rows[0]["#"] == "1"
    assert rows[0]["Theme"] == "Warm Up"
    assert rows[0]["Question"] == "Please introduce yourself"
    assert rows[0]["Observed Variable"] == "Name"

    assert rows[1]["#"] == "1"
    assert rows[1]["Observed Variable"] == "Age"

    assert rows[2]["#"] == "2"
    assert rows[2]["Question"] == "What do you think about X"


def test_normalize_dataframe_with_phase_header():
    data = [
        ["#", "Phase", "Question", "Observed Variables"],
        [1, "0. Warm-up", "a", "1"],
        ["", "", "", "2"],
        [2, "1. Awareness", "b", "3"]
    ]
    df = pd.DataFrame(data)
    rows = normalize_dataframe(df)

    assert len(rows) == 3
    assert rows[0]["Theme"] == "0. Warm-up"
    assert rows[0]["Question"] == "a"
    assert rows[0]["Observed Variable"] == "1"
    assert rows[1]["Theme"] == "0. Warm-up"
    assert rows[1]["Question"] == "a"
    assert rows[1]["Observed Variable"] == "2"
    assert rows[2]["Theme"] == "1. Awareness"
    assert rows[2]["Question"] == "b"
    assert rows[2]["Observed Variable"] == "3"


def test_excel_file_parsing(tmp_path):
    excel_path = os.path.join(tmp_path, "sample_questionnaire.xlsx")
    
    # Create sample Excel workbook with tab '2. Questionnaire'
    df_data = pd.DataFrame([
        ["#", "Theme", "Question", "Observed Variable"],
        [1, "Warm Up", "How was your day", "Mood"],
        [2, "Usability", "How easy is the app to use", "Ease of Use"]
    ])
    
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_data.to_excel(writer, sheet_name="2. Questionnaire", index=False, header=False)

    out_file = parse_and_save(excel_file=excel_path, folder_path=str(tmp_path))
    assert os.path.exists(out_file)

    val_res = validate_questionnaire(out_file)
    assert val_res["status"] == "success"
