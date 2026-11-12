"""SHA-bound view-only private Windows GUI smoke test for current frozen AaaS.

Separate from source-hosted QA. No installed binary, live ledger, finance
command, global input, process termination or printer is touched.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import qa_taraz_v106_finalfix_native_gui_20261112 as qa

qa.BUILD = qa.ARTIFACTS / "build-8498c703dc4d"
qa.EXE = qa.BUILD / "binary" / "Taraz.exe"
qa.SOURCE_SHA = "1661fab1c4e6dd66a70bd596f002a28d7db11dd30816c1ac20d0422d392abe4f"
qa.EXE_SHA = "3462cfb0dc93365e202686691eb74cc1b97dcde0333c44266191db934a42e9f4"
qa.RESULTS = qa.ARTIFACTS / "current-aaas-frozen-view-qa-20261112"

if __name__ == "__main__":
    raise SystemExit(qa.main())
