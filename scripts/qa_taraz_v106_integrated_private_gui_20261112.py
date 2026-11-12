"""Latest complete-source Windows EXE. Pinned private, VIEW-ONLY native QA.

Not an installer. No real-ledger write, finance action, process kill or desktop
switch; inherits SHA/parity, full backup readback and isolated process gates.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v106_finalfix_native_gui_20261112 as qa

qa.BUILD = qa.ARTIFACTS / "build-98e815dd931c"
qa.EXE = qa.BUILD / "binary" / "Taraz.exe"
qa.SOURCE_SHA = "9248a80030bbbfb1d794b2169a9ea0f17d70facf968de328195bccfd64a78861"
qa.EXE_SHA = "b7d27d1a44c6980a3121827eee9d502ea52a8c27f6d75f67ac67f86bddd09db7"
qa.RESULTS = qa.ARTIFACTS / "integrated-source-native-view-qa-20261112"

if __name__ == "__main__":
    raise SystemExit(qa.main())
