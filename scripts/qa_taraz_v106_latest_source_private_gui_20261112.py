"""SHA-pinned actual latest Taraz EXE. Private VIEW-ONLY native smoke test."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v106_finalfix_native_gui_20261112 as qa

qa.BUILD = qa.ARTIFACTS / 'build-357bec1519e9'
qa.EXE = qa.BUILD / 'binary' / 'Taraz.exe'
qa.SOURCE_SHA = '800134e38c7a865aa6a8dfbf48d6cf527a8cd297c1edb6d9739b4a4242fb184d'
qa.EXE_SHA = 'f369f99947ad5c7d7c436e4e5716466d5b69e2aeb807b9fba052a26664f3d978'
qa.RESULTS = qa.ARTIFACTS / 'full-source-native-view-qa-20261112'

if __name__ == '__main__':
    raise SystemExit(qa.main())
