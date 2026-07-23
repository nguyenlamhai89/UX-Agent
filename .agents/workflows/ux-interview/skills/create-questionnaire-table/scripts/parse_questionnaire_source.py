#!/usr/bin/env python3
"""
Parse Questionnaire from Google Sheet URL or local Excel file (.xlsx / .xls).
Extracts data from tab "2. Questionnaire" and formats it into canonical full-questionnaire.md.
"""

import argparse
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import openpyxl
except ImportError:
    openpyxl = None


EXPECTED_HEADERS = ["#", "Theme", "Question", "Observed Variable"]
TARGET_TAB_NAMES = ["2. Questionnaire", "2.Questionnaire", "2 Questionnaire", "Questionnaire"]


def extract_google_sheet_id(url: str) -> str:
    """Extract spreadsheet ID from Google Sheet URL."""
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if match:
        return match.group(1)
    raise ValueError(f"Could not extract Google Sheet ID from URL: {url}")


def fetch_google_sheet_csv(url: str, tab_name: str = "2. Questionnaire") -> str:
    """Fetch CSV text from public Google Sheet tab."""
    sheet_id = extract_google_sheet_id(url)
    encoded_tab = urllib.parse.quote(tab_name)
    export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={encoded_tab}"
    
    req = urllib.request.Request(export_url, headers={"User-Agent": "Antigravity/QuestionnaireParser"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8")
            return content
    except Exception as e:
        # Fallback without sheet parameter (downloads default/first tab)
        fallback_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        req_fb = urllib.request.Request(fallback_url, headers={"User-Agent": "Antigravity/QuestionnaireParser"})
        with urllib.request.urlopen(req_fb, timeout=15) as resp:
            return resp.read().decode("utf-8")


def find_target_sheet_name(sheet_names: list[str]) -> str:
    """Find sheet name matching '2. Questionnaire' or close variants."""
    for name in sheet_names:
        clean = name.strip()
        if clean in TARGET_TAB_NAMES or clean.lower() in [t.lower() for t in TARGET_TAB_NAMES]:
            return name
    
    for name in sheet_names:
        if "2." in name and "questionnaire" in name.lower():
            return name
            
    for name in sheet_names:
        if "questionnaire" in name.lower():
            return name

    # Default to first sheet if no match
    return sheet_names[0] if sheet_names else ""


def load_dataframe_from_excel(file_path: str) -> pd.DataFrame:
    """Load DataFrame from local Excel file focusing on tab '2. Questionnaire'."""
    excel_file = pd.ExcelFile(file_path)
    sheet_name = find_target_sheet_name(excel_file.sheet_names)
    df = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
    return df


def load_dataframe_from_csv_text(csv_text: str) -> pd.DataFrame:
    """Load DataFrame from CSV string."""
    return pd.read_csv(io.StringIO(csv_text), header=None)


def normalize_dataframe(df: pd.DataFrame) -> list[dict[str, str]]:
    """Locate header row and normalize columns to '#', 'Theme', 'Question', 'Observed Variable'."""
    header_idx = None
    col_mapping = {}

    # Find header row by inspecting first 15 rows
    for idx, row in df.iterrows():
        row_str = [str(val).strip().lower() for val in row.values if pd.notna(val)]
        joined = " ".join(row_str)
        if any(k in joined for k in ["question", "câu hỏi", "content", "observed", "biến quan sát"]):
            header_idx = idx
            break

    if header_idx is None:
        header_idx = 0

    header_row = df.iloc[header_idx].values
    
    # Identify column indices
    for col_i, val in enumerate(header_row):
        if pd.isna(val):
            continue
        val_lower = str(val).strip().lower()
        if val_lower in ["#", "stt", "no", "no.", "number", "index"]:
            col_mapping["#"] = col_i
        elif any(k in val_lower for k in ["theme", "topic", "chủ đề", "category"]):
            col_mapping["Theme"] = col_i
        elif any(k in val_lower for k in ["question", "câu hỏi", "content"]):
            col_mapping["Question"] = col_i
        elif any(k in val_lower for k in ["observed", "biến quan sát", "variable"]):
            col_mapping["Observed Variable"] = col_i

    # Fallback to positional mapping if required headers not detected explicitly
    if "Question" not in col_mapping or "Observed Variable" not in col_mapping:
        num_cols = len(header_row)
        if num_cols >= 4:
            col_mapping.setdefault("#", 0)
            col_mapping.setdefault("Theme", 1)
            col_mapping.setdefault("Question", 2)
            col_mapping.setdefault("Observed Variable", 3)
        elif num_cols == 3:
            col_mapping.setdefault("Theme", 0)
            col_mapping.setdefault("Question", 1)
            col_mapping.setdefault("Observed Variable", 2)
        elif num_cols == 2:
            col_mapping.setdefault("Question", 0)
            col_mapping.setdefault("Observed Variable", 1)

    data_rows = []
    curr_theme = ""
    curr_question = ""
    
    for idx in range(header_idx + 1, len(df)):
        row = df.iloc[idx]
        
        q_val = str(row.iloc[col_mapping["Question"]]).strip() if "Question" in col_mapping and pd.notna(row.iloc[col_mapping["Question"]]) else ""
        v_val = str(row.iloc[col_mapping["Observed Variable"]]).strip() if "Observed Variable" in col_mapping and pd.notna(row.iloc[col_mapping["Observed Variable"]]) else ""
        t_val = str(row.iloc[col_mapping["Theme"]]).strip() if "Theme" in col_mapping and pd.notna(row.iloc[col_mapping["Theme"]]) else ""

        # Skip completely empty rows
        if not q_val and not v_val and not t_val:
            continue
        if q_val.lower() == "question" or v_val.lower() == "observed variable":
            continue

        # Forward fill theme/question if empty due to merged cells
        if t_val:
            curr_theme = t_val
        else:
            t_val = curr_theme

        if q_val:
            curr_question = q_val
        else:
            q_val = curr_question

        if not q_val or not v_val:
            continue

        # Clean strings (remove newlines, HTML breaks, pipe characters)
        q_val = re.sub(r"<br\s*/?>|\r?\n", " ", q_val).strip()
        v_val = re.sub(r"<br\s*/?>|\r?\n", " ", v_val).strip()
        t_val = re.sub(r"<br\s*/?>|\r?\n", " ", t_val).strip()

        # Escape literal pipes
        q_val = q_val.replace("|", "\\|")
        v_val = v_val.replace("|", "\\|")
        t_val = t_val.replace("|", "\\|")

        data_rows.append({
            "Theme": t_val,
            "Question": q_val,
            "Observed Variable": v_val
        })

    # Assign continuous numbering by question
    numbered_rows = []
    question_counter = 0
    last_question = None

    for item in data_rows:
        if item["Question"] != last_question:
            question_counter += 1
            last_question = item["Question"]
        
        numbered_rows.append({
            "#": str(question_counter),
            "Theme": item["Theme"],
            "Question": item["Question"],
            "Observed Variable": item["Observed Variable"]
        })

    return numbered_rows


def generate_markdown(rows: list[dict[str, str]]) -> str:
    """Generate canonical 4-column Markdown table."""
    lines = ["# Questionnaire"]
    lines.append("| # | Theme | Question | Observed Variable |")
    lines.append("|---|-------|----------|-------------------|")

    for r in rows:
        lines.append(f"| {r['#']} | {r['Theme']} | {r['Question']} | {r['Observed Variable']} |")

    return "\n".join(lines) + "\n"


def parse_and_save(google_sheet_url: str = None, excel_file: str = None, folder_path: str = ".") -> str:
    """Parse questionnaire data and write full-questionnaire.md."""
    if not google_sheet_url and not excel_file:
        raise ValueError("Either google_sheet_url or excel_file must be provided.")

    if google_sheet_url:
        csv_text = fetch_google_sheet_csv(google_sheet_url, "2. Questionnaire")
        df = load_dataframe_from_csv_text(csv_text)
    elif excel_file:
        df = load_dataframe_from_excel(excel_file)

    rows = normalize_dataframe(df)
    if not rows:
        raise ValueError("No valid questionnaire rows extracted from input source.")

    md_content = generate_markdown(rows)
    
    interview_dir = os.path.join(folder_path, "Interview")
    os.makedirs(interview_dir, exist_ok=True)
    
    output_file = os.path.join(interview_dir, "full-questionnaire.md")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(md_content)

    return output_file


def main():
    parser = argparse.ArgumentParser(description="Parse questionnaire from Google Sheet or Excel.")
    parser.add_argument("--google-sheet-url", help="Google Sheet URL")
    parser.add_argument("--excel-file", help="Path to local Excel file (.xlsx / .xls)")
    parser.add_argument("--folder-path", default=".", help="Target project root directory")

    args = parser.parse_args()

    try:
        output_file = parse_and_save(
            google_sheet_url=args.google_sheet_url,
            excel_file=args.excel_file,
            folder_path=args.folder_path
        )
        print(json.dumps({
            "status": "success",
            "output_file": os.path.abspath(output_file)
        }, ensure_ascii=False, indent=2))
        sys.exit(0)
    except Exception as e:
        print(json.dumps({
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
