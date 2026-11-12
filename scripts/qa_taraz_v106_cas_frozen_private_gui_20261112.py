"""Private view-only GUI smoke of the exact post-CAS frozen candidate.

Do not mistake this for Save/Edit/Reopen/PDF acceptance. The audited runner
must verify immutable EXE identity, private profile and graceful owned close.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import qa_taraz_v106_finalfix_native_gui_20261112 as qa

qa.BUILD = qa.ARTIFACTS / 'build-65ee160b5e26'
qa.EXE = qa.BUILD / 'binary' / 'Taraz.exe'
qa.SOURCE_SHA = '22f3add4ca853a2eee41ec14f9b18163ba48461ec0dd8f77f2c83afcf934a189'
qa.EXE_SHA = '18d90e869d97194f1eda07d3b729d1dbbcd6f0321661d03cef651fe5e35471fd'
qa.RESULTS = qa.ARTIFACTS / 'cas-frozen-private-view-qa-20261112'

if __name__ == '__main__':
    raise SystemExit(qa.main())
