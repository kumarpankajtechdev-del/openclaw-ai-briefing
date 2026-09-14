"""Run from any working directory: python /path/to/run.py --demo."""

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).parent / "openclaw/skills/ai-briefing/scripts/briefing.py"), run_name="__main__"
    )
