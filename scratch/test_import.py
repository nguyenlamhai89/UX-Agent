import sys
try:
    from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig
    print("SUCCESS")
except ImportError as e:
    print(f"FAILED: {e}")
