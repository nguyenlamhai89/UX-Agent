import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock, call, mock_open

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))
import transcribe

@patch('transcribe.ElevenLabs')
def test_transcribe_audio_success(MockElevenLabs, tmp_path):
    mock_instance = MockElevenLabs.return_value
    mock_convert = MagicMock(spec=['text'])
    mock_convert.text = "Mocked transcription text"
    mock_instance.speech_to_text.convert.return_value = mock_convert
    
    dummy_audio = tmp_path / "test.mp3"
    dummy_audio.write_bytes(b"dummy audio data")
    
    result = transcribe.transcribe_audio(str(dummy_audio), "dummy_api_key")
    
    expected = "# INTERVIEW TRANSCRIPT: test.mp3\n\n**[00:00] [speaker_0]** <br>\nMocked transcription text"
    assert expected in result
    MockElevenLabs.assert_called_once_with(api_key="dummy_api_key")
    mock_instance.speech_to_text.convert.assert_called_once()

@patch('transcribe.time.sleep')
@patch('transcribe.ElevenLabs')
def test_transcribe_audio_retry(MockElevenLabs, mock_sleep, tmp_path):
    mock_instance = MockElevenLabs.return_value
    mock_convert = MagicMock(spec=['text'])
    mock_convert.text = "Mocked transcription text"
    
    # Fail twice, then succeed
    mock_instance.speech_to_text.convert.side_effect = [
        Exception("API Error 1"),
        Exception("API Error 2"),
        mock_convert
    ]
    
    dummy_audio = tmp_path / "test.mp3"
    dummy_audio.write_bytes(b"dummy audio data")
    
    result = transcribe.transcribe_audio(str(dummy_audio), "dummy_api_key")
    
    expected = "# INTERVIEW TRANSCRIPT: test.mp3\n\n**[00:00] [speaker_0]** <br>\nMocked transcription text"
    assert expected in result
    assert mock_instance.speech_to_text.convert.call_count == 3
    assert mock_sleep.call_count == 2
    mock_sleep.assert_has_calls([call(2), call(4)])

@patch.dict(os.environ, {"ELEVENLABS_API_KEY": "dummy_key"})
@patch('transcribe.sys.argv', ['transcribe.py', 'dummy_folder'])
@patch('transcribe.os.path.isdir', return_value=True)
@patch('transcribe.get_audio_files')
def test_main_no_audio_files(mock_get_audio_files, mock_isdir, capsys):
    mock_get_audio_files.return_value = []
    
    with pytest.raises(SystemExit) as exc_info:
        transcribe.main()
    
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    output = json.loads(captured.out.strip())
    
    assert output['status'] == 'error'
    assert output['error_code'] == 'NO_AUDIO_FILES'

@patch.dict(os.environ, {"ELEVENLABS_API_KEY": "dummy_key"})
@patch('transcribe.sys.argv', ['transcribe.py'])
def test_main_invalid_args(capsys):
    with pytest.raises(SystemExit) as exc_info:
        transcribe.main()
    
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    output = json.loads(captured.out.strip())
    
    assert output['status'] == 'error'
    assert output['error_code'] == 'INVALID_INPUT'

@patch.dict(os.environ, {"ELEVENLABS_API_KEY": "dummy_key"})
@patch('transcribe.sys.argv')
@patch('transcribe.os.path.isdir', return_value=True)
@patch('transcribe.get_audio_files')
@patch('transcribe.os.path.exists', return_value=False)
@patch('transcribe.transcribe_audio')
def test_main_success(mock_transcribe_audio, mock_exists, mock_get_audio_files, mock_isdir, mock_argv, capsys, tmp_path):
    folder = str(tmp_path)
    mock_argv.__getitem__.side_effect = lambda i: ['transcribe.py', folder][i]
    mock_argv.__len__.return_value = 2
    
    dummy_file = os.path.join(folder, "test.mp3")
    mock_get_audio_files.return_value = [dummy_file]
    mock_transcribe_audio.return_value = "Success transcription"
    
    transcribe.main()
    
    captured = capsys.readouterr()
    output = json.loads(captured.out.strip())
    
    assert output['status'] == 'success'
    assert output['data']['total'] == 1
    assert output['data']['transcripts'][0]['audio_file'] == "test.mp3"
    assert output['data']['transcripts'][0]['output_file'] == os.path.join(folder, "Interview", "transcript_test.md")

@patch.dict(os.environ, {"ELEVENLABS_API_KEY": "dummy_key"})
@patch('transcribe.sys.argv')
@patch('transcribe.os.path.isdir', return_value=True)
@patch('transcribe.get_audio_files')
@patch('transcribe.os.path.exists', return_value=True)
@patch('transcribe.transcribe_audio')
def test_main_skip_transcription(mock_transcribe_audio, mock_exists, mock_get_audio_files, mock_isdir, mock_argv, capsys, tmp_path):
    folder = str(tmp_path)
    mock_argv.__getitem__.side_effect = lambda i: ['transcribe.py', folder][i]
    mock_argv.__len__.return_value = 2
    
    dummy_file = os.path.join(folder, "test.mp3")
    mock_get_audio_files.return_value = [dummy_file]
    
    transcribe.main()
    
    mock_transcribe_audio.assert_not_called()
    
    captured = capsys.readouterr()
    output = json.loads(captured.out.strip())
    
    assert output['status'] == 'success'
    assert output['data']['total'] == 1
    assert output['data']['transcripts'][0]['audio_file'] == "test.mp3"
    assert output['data']['transcripts'][0]['output_file'] == os.path.join(folder, "Interview", "transcript_test.md")

@patch.dict(os.environ, {"ELEVENLABS_API_KEY": "dummy_key"})
@patch('transcribe.sys.argv')
@patch('transcribe.os.path.isdir', return_value=True)
@patch('transcribe.get_audio_files')
@patch('transcribe.os.path.exists', return_value=False)
@patch('transcribe.transcribe_audio')
def test_main_partial_failure(mock_transcribe_audio, mock_exists, mock_get_audio_files, mock_isdir, mock_argv, capsys, tmp_path):
    folder = str(tmp_path)
    mock_argv.__getitem__.side_effect = lambda i: ['transcribe.py', folder][i]
    mock_argv.__len__.return_value = 2
    
    file1 = os.path.join(folder, "success.mp3")
    file2 = os.path.join(folder, "fail.mp3")
    mock_get_audio_files.return_value = [file1, file2]
    
    def side_effect(path, key, keyterms=None):
        if "fail.mp3" in path:
            raise Exception("API failure")
        return "Success text"
        
    mock_transcribe_audio.side_effect = side_effect
    
    with pytest.raises(SystemExit) as exc_info:
        transcribe.main()
        
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    output = json.loads(captured.out.strip())
    
    assert output['status'] == 'error'
    assert output['error_code'] == 'API_ERROR'
    assert len(output['errors']) == 1
    assert output['errors'][0]['audio_file'] == "fail.mp3"
    assert len(output['successful_transcripts']) == 1
    assert output['successful_transcripts'][0]['audio_file'] == "success.mp3"
