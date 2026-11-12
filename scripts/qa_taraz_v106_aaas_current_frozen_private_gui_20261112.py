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

qa.BUILD = qa.ARTIFACTS / "build-69285b6c27de"
qa.EXE = qa.BUILD / "binary" / "Taraz.exe"
qa.SOURCE_SHA = "0c1938319cf7ef1c1fef0ee4b323acc50fabce15fd6791f9267cd37e3f3a76e9"
qa.EXE_SHA = "a053a7390474f642494537f2292a1a18b637f376f4b5c4962651c806ef58d91c"
qa.RESULTS = qa.ARTIFACTS / "current-aaas-frozen-view-qa-20261112"

if __name__ == "__main__":
    raise SystemExit(qa.main())
