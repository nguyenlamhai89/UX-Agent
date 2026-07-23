import os
import pytest
from unittest.mock import patch, MagicMock, mock_open

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'scripts'))

# Mock google.antigravity before importing the script
mock_antigravity = MagicMock()
mock_antigravity.Agent = MagicMock()
mock_antigravity.LocalAgentConfig = MagicMock()
mock_antigravity.CapabilitiesConfig = MagicMock()
sys.modules['google.antigravity'] = mock_antigravity

from run_interpret import interpret_phases
import asyncio

def test_interpret_phases_success(tmp_path):
    # Setup test directory
    journey_map_dir = tmp_path / "Journey Map"
    journey_map_dir.mkdir()
    
    # Create fake extracted files
    extracted_file_1 = journey_map_dir / "extracted-Awareness.md"
    extracted_file_1.write_text("Some raw Awareness data")
    
    extracted_file_2 = journey_map_dir / "extracted-Consideration.md"
    extracted_file_2.write_text("Some raw Consideration data")

    # Mock the Agent to return a pre-defined markdown table
    mock_agent_instance = MagicMock()
    
    class AsyncMockAgent:
        async def __aenter__(self):
            return mock_agent_instance
            
        async def __aexit__(self, exc_type, exc, tb):
            pass

    async def mock_chat(prompt):
        class AsyncIter:
            def __init__(self, items):
                self.items = items
                
            def __aiter__(self):
                return self
                
            async def __anext__(self):
                if not self.items:
                    raise StopAsyncIteration
                return self.items.pop(0)
                
        # Return a valid markdown table
        mock_response = """```markdown
| Category | Details |
| :--- | :--- |
| **Stage goal** | Goal 1 |
| **Stage touchpoints** | Touchpoint 1 |
| **Stage actions** | Action 1 |
| **Stage pain points** | Pain 1 |
| **Stage emotion (1-5)** | 4 - Positive 🙂 |
| **Stage opportunities & metrics** | Opp 1 |
```"""
        return AsyncIter([mock_response])

    mock_agent_instance.chat = mock_chat

    with patch('run_interpret.Agent', return_value=AsyncMockAgent()):
        result = asyncio.run(interpret_phases(str(tmp_path)))
        
    assert result["status"] == "success"
    assert len(result["result_paths"]) == 2
    
    # Check if files were created
    interpret_file_1 = journey_map_dir / "interpret-Awareness.md"
    interpret_file_2 = journey_map_dir / "interpret-Consideration.md"
    
    assert interpret_file_1.exists()
    assert interpret_file_2.exists()
    
    # Check content of one file
    content = interpret_file_1.read_text()
    assert "Stage goal" in content
    assert "Stage emotion (1-5)" in content

def test_interpret_phases_no_files(tmp_path):
    journey_map_dir = tmp_path / "Journey Map"
    journey_map_dir.mkdir()
    
    result = asyncio.run(interpret_phases(str(tmp_path)))
    
    assert result["status"] == "error"
    assert "No extracted-*.md files found" in result["message"]

def test_interpret_phases_no_dir(tmp_path):
    # Do not create Journey Map dir
    
    result = asyncio.run(interpret_phases(str(tmp_path)))
    
    assert result["status"] == "error"
    assert "Directory not found" in result["message"]

def test_interpret_phases_invalid_table(tmp_path):
    journey_map_dir = tmp_path / "Journey Map"
    journey_map_dir.mkdir()
    
    extracted_file_1 = journey_map_dir / "extracted-Awareness.md"
    extracted_file_1.write_text("Some raw Awareness data")
    
    # Mock AI response to return an invalid table (missing rows)
    mock_agent_instance = MagicMock()
    
    class AsyncMockAgent:
        async def __aenter__(self):
            return mock_agent_instance
        async def __aexit__(self, exc_type, exc, tb):
            pass

    async def mock_chat(prompt):
        class AsyncIter:
            def __init__(self, items):
                self.items = items
            def __aiter__(self):
                return self
            async def __anext__(self):
                if not self.items:
                    raise StopAsyncIteration
                return self.items.pop(0)
                
        # Table missing 'opportunities'
        mock_response = """```markdown
| Category | Details |
| :--- | :--- |
| **Stage goal** | Goal 1 |
| **Stage touchpoints** | Touchpoint 1 |
| **Stage actions** | Action 1 |
| **Stage pain points** | Pain 1 |
| **Stage emotion (1-5)** | 4 - Positive 🙂 |
```"""
        return AsyncIter([mock_response])

    mock_agent_instance.chat = mock_chat

    with patch('run_interpret.Agent', return_value=AsyncMockAgent()):
        result = asyncio.run(interpret_phases(str(tmp_path)))
        
    assert result["status"] == "error"
    assert "Table validation failed" in result["message"]

def test_interpret_phases_invalid_emotion(tmp_path):
    journey_map_dir = tmp_path / "Journey Map"
    journey_map_dir.mkdir()
    
    extracted_file_1 = journey_map_dir / "extracted-Awareness.md"
    extracted_file_1.write_text("Some raw Awareness data")
    
    mock_agent_instance = MagicMock()
    
    class AsyncMockAgent:
        async def __aenter__(self):
            return mock_agent_instance
        async def __aexit__(self, exc_type, exc, tb):
            pass

    async def mock_chat(prompt):
        class AsyncIter:
            def __init__(self, items):
                self.items = items
            def __aiter__(self):
                return self
            async def __anext__(self):
                if not self.items:
                    raise StopAsyncIteration
                return self.items.pop(0)
                
        # Emotion score is "6" (out of 1-5 range)
        mock_response = """```markdown
| Category | Details |
| :--- | :--- |
| **Stage goal** | Goal 1 |
| **Stage touchpoints** | Touchpoint 1 |
| **Stage actions** | Action 1 |
| **Stage pain points** | Pain 1 |
| **Stage emotion (1-5)** | 6 |
| **Stage opportunities & metrics** | Opp 1 |
```"""
        return AsyncIter([mock_response])

    mock_agent_instance.chat = mock_chat

    with patch('run_interpret.Agent', return_value=AsyncMockAgent()):
        result = asyncio.run(interpret_phases(str(tmp_path)))
        
    assert result["status"] == "error"
    assert "Stage emotion must contain a numeric score from 1-5" in result["message"]

def test_interpret_phases_skip_logic(tmp_path):
    journey_map_dir = tmp_path / "Journey Map"
    journey_map_dir.mkdir()
    
    extracted_file_1 = journey_map_dir / "extracted-Awareness.md"
    extracted_file_1.write_text("Some raw Awareness data")
    
    # Pre-create output file so skip check matches
    interpret_file_1 = journey_map_dir / "interpret-Awareness.md"
    interpret_file_1.write_text("Some existing table")
    
    # Run without force
    result = asyncio.run(interpret_phases(str(tmp_path), force=False))
    
    assert result["status"] == "success"
    assert "Skipping AI processing" in result["message"]
    assert len(result["result_paths"]) == 1
