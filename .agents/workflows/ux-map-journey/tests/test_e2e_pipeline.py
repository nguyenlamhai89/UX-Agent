import os
import shutil
import subprocess
import pytest
from pathlib import Path
import sys
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

# Add extract-map and interpret-phases scripts to path so patch can resolve 'Agent' during import
base_dir = Path(__file__).parent.parent
sys.path.append(str(base_dir / "skills" / "extract-map" / "scripts"))
sys.path.append(str(base_dir / "skills" / "interpret-phases" / "scripts"))

# Setup mock for google.antigravity and google.genai
mock_google = MagicMock()
mock_antigravity = MagicMock()
mock_agent = MagicMock()
mock_config = MagicMock()
mock_cap = MagicMock()
mock_antigravity.Agent = mock_agent
mock_antigravity.LocalAgentConfig = mock_config
mock_antigravity.CapabilitiesConfig = mock_cap

mock_genai = MagicMock()
mock_genai_types = MagicMock()

sys.modules['google'] = mock_google
sys.modules['google.antigravity'] = mock_antigravity
sys.modules['google.genai'] = mock_genai
sys.modules['google.genai.types'] = mock_genai_types

class MockAgentContext:
    def __init__(self, *args, **kwargs):
        self.mock_agent = AsyncMock()
        
        class AsyncIterator:
            def __init__(self, items):
                self.items = items
                self.index = 0

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.index < len(self.items):
                    item = self.items[self.index]
                    self.index += 1
                    return item
                else:
                    raise StopAsyncIteration

        mock_response = MagicMock()
        valid_table = """```markdown
# Interpret - Phase
| Category | Details |
| :--- | :--- |
| **Stage goal** | Goal |
| **Stage touchpoints** | Touchpoints |
| **Stage actions** | Actions |
| **Stage pain points** | Pain points |
| **Stage emotion (1-5)** | 3 - Neutral 😐 |
| **Stage opportunities & metrics** | Opportunities |
```"""
        mock_response.__aiter__ = lambda x: AsyncIterator([valid_table])
        self.mock_agent.chat.return_value = mock_response

    async def __aenter__(self):
        return self.mock_agent

    async def __aexit__(self, exc_type, exc, tb):
        pass

@pytest.fixture
def mock_workspace(tmp_path):
    mock_dir = Path(__file__).parent / "mock-dataset"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    # Copy template transcript
    shutil.copy(mock_dir / "mapped-transcript.md", workspace / "mapped-transcript.md")
    return workspace

@patch('run_interpret.Agent', new=MockAgentContext)
def test_e2e_pipeline(mock_workspace):
    from extract_map import extract_map
    from run_interpret import interpret_phases

    # Step 1: Run extract-phases (subprocess)
    phases_script = base_dir / "skills" / "extract-phases" / "scripts" / "extract_all_phases.py"
    python_exec = sys.executable
    
    res1 = subprocess.run([python_exec, str(phases_script), "--folder-path", str(mock_workspace)], capture_output=True, text=True)
    assert res1.returncode == 0, f"Extraction failed: {res1.stderr}"
    
    # Verify phases folders/files exist
    jm_dir = mock_workspace / "Journey Map"
    assert jm_dir.exists()
    assert (jm_dir / "extracted-awareness.md").exists()
    assert (jm_dir / "extracted-consideration.md").exists()
    assert (jm_dir / "extracted-decision-making.md").exists()
    assert (jm_dir / "extracted-usage.md").exists()
    assert (jm_dir / "extracted-advocacy.md").exists()
    
    # Step 2: Run interpret-phases (direct function call with mock Agent context)
    result_interpret = asyncio.run(interpret_phases(str(mock_workspace)))
    assert result_interpret["status"] == "success"
    
    # Verify interpret-*.md files exist
    assert (jm_dir / "interpret-awareness.md").exists()
    assert (jm_dir / "interpret-consideration.md").exists()
    assert (jm_dir / "interpret-decision-making.md").exists()
    assert (jm_dir / "interpret-usage.md").exists()
    assert (jm_dir / "interpret-advocacy.md").exists()

    # Step 3: Run extract-map (direct function call without mock Agent context)
    result = asyncio.run(extract_map(str(mock_workspace)))
    assert result["status"] == "success"
    
    # Verify journey-map.md is generated
    jm_file = jm_dir / "journey-map.md"
    assert jm_file.exists()
    content = jm_file.read_text(encoding='utf-8')
    assert "# Customer Journey Map" in content
    assert "Stage 1: Awareness" in content
