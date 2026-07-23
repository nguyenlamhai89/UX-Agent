import os
import subprocess
import pytest

MOCK_MARKDOWN = """| # | Theme | Question | Response |
|---|---|---|---|
| 1 | 1. Awareness | How did you hear? | From a friend |
| 2 | 2. Consideration | Why choose us? | Good reviews |
| 3 | Awareness | Another channel | Online Ad |
| 4 | Usage | How do you use it? | Daily |
| 5 | 5. Advocacy | Recommend us? | Yes |
| 6 | 3. Decision Making | Decision? | Made it |
| 7 | Invalid Theme | Test | Test |
| 8 | Only 1 Col |
"""

@pytest.fixture
def mock_folder(tmp_path):
    folder = tmp_path / "mock_project"
    folder.mkdir()
    file_path = folder / "mapped-transcript.md"
    file_path.write_text(MOCK_MARKDOWN, encoding='utf-8')
    return folder

def test_extract_all_phases(mock_folder):
    script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'extract_all_phases.py')
    
    result = subprocess.run(['python3', script_path, '--folder-path', str(mock_folder)], capture_output=True, text=True)
    assert result.returncode == 0
    
    jm_dir = mock_folder / "Journey Map"
    assert jm_dir.exists()
    
    # Check Awareness
    awareness_file = jm_dir / "extracted-awareness.md"
    assert awareness_file.exists()
    content = awareness_file.read_text(encoding='utf-8')
    lines = content.strip().split('\n')
    assert len(lines) == 4 # Header, Separator, 2 data rows
    assert '1. Awareness' in content
    assert 'Awareness |' in content
    
    # Check Consideration
    consideration_file = jm_dir / "extracted-consideration.md"
    assert consideration_file.exists()
    content = consideration_file.read_text(encoding='utf-8')
    lines = content.strip().split('\n')
    assert len(lines) == 3 # Header, Separator, 1 data row
    assert '2. Consideration' in content
    
    # Check Decision Making
    decision_file = jm_dir / "extracted-decision-making.md"
    assert decision_file.exists()
    content = decision_file.read_text(encoding='utf-8')
    lines = content.strip().split('\n')
    assert len(lines) == 3
    assert '3. Decision Making' in content
    
    # Check Usage
    usage_file = jm_dir / "extracted-usage.md"
    assert usage_file.exists()
    content = usage_file.read_text(encoding='utf-8')
    lines = content.strip().split('\n')
    assert len(lines) == 3
    assert 'Usage' in content
    
    # Check Advocacy
    advocacy_file = jm_dir / "extracted-advocacy.md"
    assert advocacy_file.exists()
    content = advocacy_file.read_text(encoding='utf-8')
    lines = content.strip().split('\n')
    assert len(lines) == 3
    assert '5. Advocacy' in content
