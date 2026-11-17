"""Latest frozen current-source Taraz EXE: PINNED private VIEW-ONLY QA."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v106_finalfix_native_gui_20261112 as qa

qa.BUILD = qa.ARTIFACTS / "build-7e54afa3c1a5"
qa.EXE = qa.BUILD / "binary" / "Taraz.exe"
qa.SOURCE_SHA = "91b33ad118c8b855dc1207d491b7fc01675a8d1caa5fc30717beb4d4a3cfc642"
qa.EXE_SHA = "e7020686f15d67b2ae888caef3c65b271494ec98a672fc902f390f35ae33ee63"
qa.RESULTS = qa.ARTIFACTS / "latest-custom-column-native-view-qa-20261112"

if __name__ == "__main__":
    raise SystemExit(qa.main())
