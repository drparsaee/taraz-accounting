"""Unsaved, synthetic input on an owned PRIVATE native window only.

Uses the pinned current-source EXE and safe QA clone. No form save, invoice
issue, finance command, global input, active desktop switch or process kill.
"""
from __future__ import annotations
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v106_current_private_gui_20261112 as current

qa = current.qa
qa.RESULTS = qa.ARTIFACTS / "current-source-native-input-probe-20261112"
# A previous dirty-form close was vetoed. Never spawn another QA-owned copy
# of the same EXE until that exact process has exited by an approved route.
_validated_candidate = qa.candidate
def candidate_without_orphan():
    from pathlib import Path
    import psutil
    expected = qa.EXE.resolve()
    for process in psutil.process_iter(["pid", "name"]):
        try:
            if (process.info.get("name") or "").casefold() == "taraz.exe" and \
                    Path(process.exe()).resolve() == expected:
                raise qa.Blocked("Exact QA EXE is already active: native test will not spawn another")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return _validated_candidate()
qa.candidate = candidate_without_orphan
anchor = " $out.status='PRIVATE_OWNED_UIA_RECORDED'"
script = r'''
 $out.privateUnsavedInputProbe=@{performed=$false;results=@{};noSaveAttempted=$true}
 if($out.invoiceBeginnerOpened -and $out.invoiceBeginnerContentVisible){
  # The three exact named controls exist on this QA-owned private WebView.
  # Do not access any customer list or read existing customer names.
  $targets=@(
   @('شرح ردیف 1','آزمون محلی بدون ثبت'),
   @('تعداد ردیف 1','2'),
   @('قیمت ردیف 1','9000')
  )
  foreach($target in $targets){
   $label=[string]$target[0];$value=[string]$target[1]
   $elements=@(Named $label | Where-Object {
     $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit -and
     $_.Current.IsEnabled
   })
   if($elements.Count -ne 1){
    $out.privateUnsavedInputProbe.results[$label]=@{count=$elements.Count;set=$false;match=$false}
    continue
   }
   $control=$elements[0];$pattern=$null
   try {
    if(-not $control.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,
      [ref]$pattern)){throw 'ValuePattern unavailable'}
    $pattern.SetValue($value)
    Start-Sleep -Milliseconds 200
    $readback=[string]$pattern.Current.Value
    $out.privateUnsavedInputProbe.results[$label]=@{count=1;set=$true;match=($readback -eq $value)}
    $out.privateUnsavedInputProbe.performed=$true
   }catch{
    $out.privateUnsavedInputProbe.results[$label]=@{count=1;set=$false;match=$false;
      error=$_.Exception.GetType().Name}
   }
  }
 }
'''
if qa.PRIVATE_UIA.count(anchor) != 1:
    raise RuntimeError("Private native input probe anchor changed")
qa.PRIVATE_UIA = qa.PRIVATE_UIA.replace(anchor, script + anchor, 1)

if __name__ == "__main__":
    raise SystemExit(qa.main())
