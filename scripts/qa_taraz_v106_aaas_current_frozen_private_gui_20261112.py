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

qa.BUILD = qa.ARTIFACTS / "build-7f17dbf72519"
qa.EXE = qa.BUILD / "binary" / "Taraz.exe"
qa.SOURCE_SHA = "23bd9f26a7954220f0e3720483a355a9442f15a0505960968d5a5edd1bd09ff7"
qa.EXE_SHA = "301dfede5eeaa597f73c03b86d17fcee6f23083ac78e3945b161aef547937ede"
qa.RESULTS = qa.ARTIFACTS / "current-aaas-frozen-view-qa-20261112"

if __name__ == "__main__":
    raise SystemExit(qa.main())
