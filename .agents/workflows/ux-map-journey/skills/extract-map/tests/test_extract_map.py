import os
import pytest
from unittest.mock import patch, MagicMock
import sys
import asyncio

# Add scripts directory to path to import extract_map
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))

from extract_map import extract_map

@patch('extract_map.glob_sync')
@patch('extract_map.os.path.exists')
@patch('builtins.open', new_callable=MagicMock)
def test_extract_map_success(mock_open, mock_exists, mock_glob):
    def exists_side_effect(path):
        if "journey-map.md" in path:
            return False
        return True
    mock_exists.side_effect = exists_side_effect
    
    mock_glob.return_value = ['/path/to/Journey Map/interpret-awareness.md', '/path/to/Journey Map/interpret-decision-making.md']
    
    file_handle = MagicMock()
    file_handle.__enter__.return_value.read.return_value = """
| Category | Details |
| :--- | :--- |
| **Stage goal** | Goal 1 |
| **Stage touchpoints** | Touchpoint 1 |
| **Stage actions** | Action 1 |
| **Stage pain points** | Pain 1 |
| **Stage emotion (1-5)** | 4 |
| **Stage opportunities & metrics** | Opp 1 |
"""
    mock_open.return_value = file_handle
    
    result = asyncio.run(extract_map('/path/to'))
    
    assert result['status'] == 'success'
    assert "deterministically" in result['message']
    assert "Warnings" in result['message']
    mock_glob.assert_called_once_with('/path/to/Journey Map/interpret-*.md')
    assert mock_open.call_count >= 2

@patch('extract_map.os.path.exists')
def test_extract_map_no_dir(mock_exists):
    mock_exists.return_value = False
    
    result = asyncio.run(extract_map('/path/to'))
    
    assert result['status'] == 'error'
    assert 'Directory not found' in result['message']

@patch('extract_map.glob_sync')
@patch('extract_map.os.path.exists')
@patch('builtins.open', new_callable=MagicMock)
def test_extract_map_idempotency_skip(mock_open, mock_exists, mock_glob):
    mock_exists.side_effect = lambda path: True
    mock_glob.return_value = ['/path/to/Journey Map/interpret-awareness.md']
    
    file_handle = MagicMock()
    table_content = """
| Category | Details |
| :--- | :--- |
| **Stage goal** | Goal 1 |
| **Stage touchpoints** | Touchpoint 1 |
| **Stage actions** | Action 1 |
| **Stage pain points** | Pain 1 |
| **Stage emotion (1-5)** | 4 |
| **Stage opportunities & metrics** | Opp 1 |
"""
    final_map_content = """# Customer Journey Map

| Dimension | Stage 1: Awareness | Stage 2: Consideration | Stage 3: Decision Making | Stage 4: Usage | Stage 5: Advocacy |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Stage Goal** | Goal 1 |  |  |  |  |
| **Stage Touchpoints** | Touchpoint 1 |  |  |  |  |
| **Stage Actions** | Action 1 |  |  |  |  |
| **Stage Pain Points** | Pain 1 |  |  |  |  |
| **Stage Emotion (1-5)** | 4 |  |  |  |  |
| **Stage Opportunities & Metrics** | Opp 1 |  |  |  |  |
"""
    file_handle.__enter__.return_value.read.side_effect = [table_content, final_map_content]
    mock_open.return_value = file_handle
    
    result = asyncio.run(extract_map('/path/to'))
    
    assert result['status'] == 'success'
    assert "already up to date. Skipping processing" in result['message']

@patch('extract_map.glob_sync')
@patch('extract_map.os.path.exists')
@patch('builtins.open', new_callable=MagicMock)
def test_extract_map_direct_journey_map_path(mock_open, mock_exists, mock_glob):
    def exists_side_effect(path):
        if "journey-map.md" in path:
            return False
        return True
    mock_exists.side_effect = exists_side_effect
    
    mock_glob.return_value = ['/path/to/Journey Map/interpret-awareness.md']
    
    file_handle = MagicMock()
    file_handle.__enter__.return_value.read.return_value = """
| Category | Details |
| :--- | :--- |
| **Stage goal** | Goal 1 |
| **Stage touchpoints** | Touchpoint 1 |
| **Stage actions** | Action 1 |
| **Stage pain points** | Pain 1 |
| **Stage emotion (1-5)** | 4 |
| **Stage opportunities & metrics** | Opp 1 |
"""
    mock_open.return_value = file_handle
    
    result = asyncio.run(extract_map('/path/to/Journey Map'))
    
    assert result['status'] == 'success'
    mock_glob.assert_called_once_with('/path/to/Journey Map/interpret-*.md')

@patch('extract_map.parse_markdown_table_sync')
@patch('extract_map.glob_sync')
@patch('extract_map.os.path.exists')
@patch('builtins.open', new_callable=MagicMock)
def test_extract_map_cell_sanitization(mock_open, mock_exists, mock_glob, mock_parse):
    def exists_side_effect(path):
        if "journey-map.md" in path:
            return False
        return True
    mock_exists.side_effect = exists_side_effect
    
    mock_glob.return_value = ['/path/to/Journey Map/interpret-awareness.md']
    
    mock_parse.return_value = {
        "goal": "Goal with | a pipe and\na newline",
        "touchpoints": "Touchpoint 1",
        "actions": "Action 1",
        "pain points": "Pain 1",
        "emotion": "4",
        "opportunities": "Opp 1"
    }
    
    result = asyncio.run(extract_map('/path/to'))
    assert result['status'] == 'success'
    
    write_calls = [call for call in mock_open.mock_calls if call[0] == '().__enter__().write']
    assert len(write_calls) > 0
    written_content = write_calls[-1][1][0]
    assert "Goal with \\| a pipe and<br>a newline" in written_content

@patch('extract_map.glob_sync')
@patch('extract_map.os.path.exists')
@patch('builtins.open', new_callable=MagicMock)
def test_extract_map_filesystem_error(mock_open, mock_exists, mock_glob):
    def exists_side_effect(path):
        if "journey-map.md" in path:
            return False
        return True
    mock_exists.side_effect = exists_side_effect
    
    mock_glob.return_value = ['/path/to/Journey Map/interpret-awareness.md']
    
    file_handle = MagicMock()
    file_handle.__enter__.return_value.read.return_value = """
| Category | Details |
| :--- | :--- |
| **Stage goal** | Goal 1 |
| **Stage touchpoints** | Touchpoint 1 |
| **Stage actions** | Action 1 |
| **Stage pain points** | Pain 1 |
| **Stage emotion (1-5)** | 4 |
| **Stage opportunities & metrics** | Opp 1 |
"""
    file_handle.__enter__.return_value.write.side_effect = PermissionError("Permission denied")
    mock_open.return_value = file_handle
    
    result = asyncio.run(extract_map('/path/to'))
    assert result['status'] == 'error'
    assert 'filesystem error' in result['message']
