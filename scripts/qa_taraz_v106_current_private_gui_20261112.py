"""Reuse the audited no-finance-input native viewer for the current source fix.

This is VIEW-ONLY; the immutable current-source EXE, backup and installation
identity must all pass the existing runner's fail-closed checks first.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v106_finalfix_native_gui_20261112 as qa

qa.BUILD = qa.ARTIFACTS / "build-250eead995ca"
qa.EXE = qa.BUILD / "binary" / "Taraz.exe"
qa.SOURCE_SHA = "b6d63424fbccda75d6fe2699c7ffc07442d403d4e5564b5563389b06eea45362"
qa.EXE_SHA = "ca290b6c250be0d2c09c92502426d0649343255a019dd1a93f2c2cb18671d308"
qa.RESULTS = qa.ARTIFACTS / "current-source-native-view-qa-20261112"

# Read only the availability of named, owned invoice controls and their native
# automation patterns. Never read customer text, ledger values or credentials.
_anchor = " $out.status='PRIVATE_OWNED_UIA_RECORDED'"
_probe = r'''
 $out.nativeInputCapability=@{}
 if($out.invoiceBeginnerOpened -and $out.invoiceBeginnerContentVisible){
  foreach($name in @('شرح ردیف 1','تعداد ردیف 1','قیمت ردیف 1',
    'مشتری فاکتور','ذخیره پیش‌نویس فاکتور','حالت حرفه‌ای')) {
   try {
    $matches=@(Named $name)
    $formats=@()
    foreach($element in $matches){
     $value=$null;$select=$null;$invoke=$null
     $formats+=@{
      control=[string]$element.Current.ControlType.ProgrammaticName;
      valuePattern=[bool]$element.TryGetCurrentPattern(
       [System.Windows.Automation.ValuePattern]::Pattern,[ref]$value);
      selectionPattern=[bool]$element.TryGetCurrentPattern(
       [System.Windows.Automation.SelectionPattern]::Pattern,[ref]$select);
      invokePattern=[bool]$element.TryGetCurrentPattern(
       [System.Windows.Automation.InvokePattern]::Pattern,[ref]$invoke)
     }
    }
    $out.nativeInputCapability[$name]=@{count=$matches.Count;patterns=$formats}
   }catch {$out.nativeInputCapability[$name]=@{error=$_.Exception.GetType().Name}}
  }
 }
'''
if qa.PRIVATE_UIA.count(_anchor) != 1:
    raise RuntimeError("Read-only private QA injection anchor changed")
qa.PRIVATE_UIA = qa.PRIVATE_UIA.replace(_anchor, _probe + _anchor, 1)

if __name__ == "__main__":
    raise SystemExit(qa.main())
