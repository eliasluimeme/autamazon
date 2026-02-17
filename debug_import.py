import sys
import os
import traceback

# Configure paths same as run.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../social-ui')))

print("sys.path:", sys.path)

try:
    from modules.opsec_workflow import OpSecBrowserManager
    print("Import Successful!")
except ImportError:
    print("Import Failed!")
    traceback.print_exc()
except Exception:
    print("An error occurred!")
    traceback.print_exc()
