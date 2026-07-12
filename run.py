import os
import sys
from pathlib import Path

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent
    os.chdir(project_root)
    os.system(
        f'"{sys.executable}" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000'
    )
