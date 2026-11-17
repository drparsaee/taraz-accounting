"""Real CURRENT Taraz.exe native QA: isolated draft create and SQLite readback.

Never touches installed Taraz or live finance. Registers only one synthetic QA
customer in the already copied private company ledger. No issue/approval/post,
no global keyboard/mouse, no process kill. Fails closed on incomplete UIA.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_taraz_v106_integrated_private_gui_20261112 as integrated
from scripts import qa_taraz_v106_safe_orphan_recovery_20261112 as safety
from standalone_accounting import StandaloneAccountingStore

qa = integrated.qa
qa.RESULTS = qa.ARTIFACTS / "integrated-source-native-draft-qa-20261112"

QA_PARTY_ID = "QA-NATIVE-CUSTOMER-1112"
QA_PARTY_NAME = "مشتری حضوری"
QA_LINE = "سند آزمون بومی ایزوله"
ACCOUNTS = {"qa-native-test": {"username": "qa-native-test", "role": "admin",
                                "financeEdit": True, "financeView": True}}
_clone = qa.native.clone_offline_snapshot


def seeded_clone(work):
    runtime, paths = _clone(work)
    ledger = paths["roaming"] / "standalone-accounting.sqlite3"
    store = StandaloneAccountingStore(ledger, default_currency="RIAL")
    before = store.read(actor="qa-native-test", accounts=ACCOUNTS)
    if QA_PARTY_ID in before["view"]["parties"]:
        raise RuntimeError("QA test customer ID already exists in cloned ledger")
    # The existing UI auto-selects a walk-in customer only if there is exactly
    # one. Never select or silently edit an original party from the snapshot.
    preexisting_walkins = [p for p in before["view"]["parties"].values() if
                           str(p.get("name", "")).strip() in ("مشتری حضوری", "مشتری متفرقه")]
    if preexisting_walkins:
        raise RuntimeError("Original QA snapshot already has walk-in customers")
    result = store.command({
        "type": "party.register", "eventId": "qa-native-party-" + uuid.uuid4().hex,
        "partyId": QA_PARTY_ID, "name": QA_PARTY_NAME, "kind": "customer",
    }, actor="qa-native-test", accounts=ACCOUNTS,
        expected_revision=before["revision"], now=datetime.now(timezone.utc).isoformat())
    receipt = {"beforeRevision": before["revision"],
               "seedRevision": result["revision"], "seedPartyId": QA_PARTY_ID,
               "originalJournals": len(before["view"]["journals"]),
               "seedSha256": hashlib.sha256(ledger.read_bytes()).hexdigest()}
    (work / "qa-native-seed.json").write_text(json.dumps(receipt, indent=2) + "\n",
                                               encoding="utf-8")
    return runtime, paths


_anchor = " $out.status='PRIVATE_OWNED_UIA_RECORDED'"
_native_submit = r'''
 $out.nativeQaDraft=@{syntheticOnly=$true;partyIdSelected=$false;
   dataFieldsSet=@{};saveButtonEnabled=$false;saveInvoked=$false;
   nativeErrors=@{};noIssueOrApprove=$true}
 if($out.invoiceBeginnerOpened -and $out.invoiceBeginnerContentVisible){
  # UI handler selects a uniquely registered walk-in customer automatically.
  # This avoids an unreliable native HTML <select> accessibility popup.
  $walkin=@(Named 'مشتری حضوری'|Where-Object{
    $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and
    $_.Current.IsEnabled
  })
  $out.nativeQaDraft.walkinButtonCount=$walkin.Count
  if($walkin.Count -eq 1){
    try {
     $out.nativeQaDraft.walkinInitiallyOffscreen=[bool]$walkin[0].Current.IsOffscreen
     $scrollItem=$null
     if($walkin[0].TryGetCurrentPattern(
       [System.Windows.Automation.ScrollItemPattern]::Pattern,[ref]$scrollItem)){
       $scrollItem.ScrollIntoView()
       $out.nativeQaDraft.scrollItemPatternUsed=$true
       Start-Sleep -Milliseconds 300
     }
     # If the page has no ScrollItemPattern, only the *private* owned WebView
     # HWND receives a bounded sequence of wheel messages. No desktop switch.
     if($walkin[0].Current.IsOffscreen){
       $rootBounds=$root.Current.BoundingRectangle
       $px=[int][Math]::Round($rootBounds.X+$rootBounds.Width*.76)
       $py=[int][Math]::Round($rootBounds.Y+$rootBounds.Height*.64)
       $widgets=New-Object 'System.Collections.Generic.List[System.IntPtr]'
       $cb=[TarazPrivateInput+Callback]{
        param($hwnd,$ignore)
        $owner=[uint32]0
        [void][TarazPrivateInput]::GetWindowThreadProcessId($hwnd,[ref]$owner)
        if($ids -notcontains [int]$owner){return $true}
        $cls=New-Object System.Text.StringBuilder 140
        [void][TarazPrivateInput]::GetClassName($hwnd,$cls,$cls.Capacity)
        if($cls.ToString() -ne 'Chrome_RenderWidgetHostHWND'){return $true}
        $rect=New-Object TarazPrivateInput+Rect
        if([TarazPrivateInput]::GetWindowRect($hwnd,[ref]$rect) -and
           $px -ge $rect.L -and $px -lt $rect.R -and
           $py -ge $rect.T -and $py -lt $rect.B){$widgets.Add($hwnd)}
        return $true
       }
       [void][TarazPrivateInput]::EnumChildWindows(
         [IntPtr]$root.Current.NativeWindowHandle,$cb,[IntPtr]::Zero)
       $out.nativeQaDraft.ownedScrollWidgetCount=$widgets.Count
       if($widgets.Count -eq 1){
        $lp=[IntPtr]::new([int]((($py -band 0xffff) -shl 16) -bor ($px -band 0xffff)))
        $wp=[IntPtr]::new([int](-120 -shl 16))
        $wheelCount=0
        foreach($step in 1..36){
          if(-not $walkin[0].Current.IsOffscreen){break}
          if(-not [TarazPrivateInput]::PostMessage(
             $widgets[0],[uint32]0x020A,$wp,$lp)){break}
          $wheelCount++
          Start-Sleep -Milliseconds 65
        }
        $out.nativeQaDraft.privateWheelPosts=$wheelCount
       }
     }
     $out.nativeQaDraft.walkinOffscreenAfterScroll=[bool]$walkin[0].Current.IsOffscreen
     if($out.nativeQaDraft.walkinOffscreenAfterScroll){
       throw 'Walkin button remains offscreen after bounded private scroll'
     }
     $out.nativeQaDraft.walkinActivate=Activate 'مشتری حضوری'
     Start-Sleep -Milliseconds 550
     $out.nativeQaDraft.partyIdSelected=Has @('مشتری حضوری ثبت‌شده انتخاب شد: مشتری حضوری')
     if(-not $out.nativeQaDraft.partyIdSelected){
       # Chromium exposes the button but does not implement UIA InvokePattern.
       # Deliver a single mouse click ONLY to the exact owned render HWND.
       $out.nativeQaDraft.directClickStage='bounds'
       $b=$walkin[0].Current.BoundingRectangle
       $cx=[int][Math]::Round($b.X+$b.Width/2)
       $cy=[int][Math]::Round($b.Y+$b.Height/2)
       $out.nativeQaDraft.buttonBounds=@{x=$cx;y=$cy;width=[int]$b.Width;height=[int]$b.Height}
       if($b.Width -lt 22 -or $b.Width -gt 500 -or $b.Height -lt 12 -or $b.Height -gt 120){
         throw 'Native walk-in click target fails size contract'
       }
       $out.nativeQaDraft.directClickStage='owned-hwnd'
       $matches=New-Object 'System.Collections.Generic.List[System.IntPtr]'
       $cb=[TarazPrivateInput+Callback]{
        param($hwnd,$ignore)
        $owner=[uint32]0
        [void][TarazPrivateInput]::GetWindowThreadProcessId($hwnd,[ref]$owner)
        if($ids -notcontains [int]$owner){return $true}
        $cls=New-Object System.Text.StringBuilder 140
        [void][TarazPrivateInput]::GetClassName($hwnd,$cls,$cls.Capacity)
        if($cls.ToString() -ne 'Chrome_RenderWidgetHostHWND'){return $true}
        $rect=New-Object TarazPrivateInput+Rect
        if([TarazPrivateInput]::GetWindowRect($hwnd,[ref]$rect) -and
           $cx -ge $rect.L -and $cx -lt $rect.R -and
           $cy -ge $rect.T -and $cy -lt $rect.B){$matches.Add($hwnd)}
        return $true
       }
       [void][TarazPrivateInput]::EnumChildWindows(
         [IntPtr]$root.Current.NativeWindowHandle,$cb,[IntPtr]::Zero)
       $out.nativeQaDraft.clickOwnedWidgetCount=$matches.Count
       if($matches.Count -eq 1){
         $p=New-Object TarazPrivateInput+Point
         $p.X=$cx;$p.Y=$cy
         if([TarazPrivateInput]::ScreenToClient($matches[0],[ref]$p) -and
            $p.X -ge 0 -and $p.Y -ge 0 -and $p.X -lt 32767 -and $p.Y -lt 32767){
           $lp=[IntPtr]::new([int](($p.Y -shl 16) -bor $p.X))
           $down=[TarazPrivateInput]::PostMessage($matches[0],[uint32]0x0201,
             [IntPtr]::new(1),$lp)
           $up=[TarazPrivateInput]::PostMessage($matches[0],[uint32]0x0202,
             [IntPtr]::Zero,$lp)
           $out.nativeQaDraft.directClickPosted=($down -and $up)
           Start-Sleep -Milliseconds 600
           $out.nativeQaDraft.partyIdSelected=Has @('مشتری حضوری ثبت‌شده انتخاب شد: مشتری حضوری')
         }
       }
       $out.nativeQaDraft.directClickStage='completed'
     }
    }catch{$out.nativeQaDraft.nativeErrors['customer']=$_.Exception.GetType().Name}
  }
  $fields=@(
   @('شرح ردیف 1','سند آزمون بومی ایزوله'),
   @('تعداد ردیف 1','2'),
   @('قیمت ردیف 1','9000')
  )
  foreach($field in $fields){
   $name=[string]$field[0];$value=[string]$field[1]
   $controls=@(Named $name|Where-Object{
    $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit -and
    $_.Current.IsEnabled
   })
   if($controls.Count -ne 1){$out.nativeQaDraft.dataFieldsSet[$name]=$false;continue}
   try {
    $pattern=$null
    if(-not $controls[0].TryGetCurrentPattern(
      [System.Windows.Automation.ValuePattern]::Pattern,[ref]$pattern)){
      throw 'Unavailable value pattern'
    }
    $pattern.SetValue($value)
    Start-Sleep -Milliseconds 180
    $out.nativeQaDraft.dataFieldsSet[$name]=($pattern.Current.Value -eq $value)
   }catch{
    $out.nativeQaDraft.dataFieldsSet[$name]=$false
    $out.nativeQaDraft.nativeErrors[$name]=$_.Exception.GetType().Name
   }
  }
  Start-Sleep -Milliseconds 500
  $save=@(Named 'ذخیره پیش‌نویس فاکتور'|Where-Object{
    $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button
  })
  if($save.Count -eq 1){
   $out.nativeQaDraft.saveButtonEnabled=[bool]$save[0].Current.IsEnabled
   $allFieldsSet=@($out.nativeQaDraft.dataFieldsSet.Values|Where-Object{$_ -ne $true}).Count -eq 0
   if($out.nativeQaDraft.partyIdSelected -and $allFieldsSet -and
      $out.nativeQaDraft.saveButtonEnabled){
    try {
     $invoke=$null
     if(-not $save[0].TryGetCurrentPattern(
       [System.Windows.Automation.InvokePattern]::Pattern,[ref]$invoke)){
       throw 'No safe submit invocation'
     }
     $invoke.Invoke()
     $out.nativeQaDraft.saveInvoked=$true
     $out.noFinanceActionAttempted=$false
     Start-Sleep -Milliseconds 1100
    }catch{$out.nativeQaDraft.nativeErrors['save']=$_.Exception.GetType().Name}
   }
  }
 }
'''


def main():
    if qa.PRIVATE_UIA.count(_anchor) != 1:
        raise RuntimeError("Native QA injection anchor changed")
    allowed = "$name -in @('بازکردن فهرست بخش‌های تراز','سفارش‌ها','طراحی فرم فاکتور')"
    if qa.PRIVATE_UIA.count(allowed) != 1:
        raise RuntimeError("QA native allowlist ownership anchor changed")
    qa.PRIVATE_UIA = qa.PRIVATE_UIA.replace(allowed, allowed[:-1] + ",'مشتری حضوری')", 1)
    qa.PRIVATE_UIA = qa.PRIVATE_UIA.replace(_anchor, _native_submit + _anchor, 1)
    qa.native.clone_offline_snapshot = seeded_clone
    report_file = qa.run()
    report = json.loads(report_file.read_text(encoding="utf-8"))
    receipt = json.loads((report_file.parent / "qa-native-seed.json").read_text(encoding="utf-8"))
    ledger = report_file.parent / "private-profile" / "qa" / "qa-runtime" / "roaming" / "Taraz" / "standalone-accounting.sqlite3"
    store = StandaloneAccountingStore(ledger, default_currency="RIAL")
    state = store.read(actor="qa-native-test", accounts=ACCOUNTS)
    matches = [item for item in state["view"]["invoices"].values() if
               item.get("partyId") == QA_PARTY_ID and any(
                   line.get("description") == QA_LINE for line in item.get("lines", []))]
    exact = len(matches) == 1 and matches[0].get("status") == "draft" and \
        matches[0].get("total") == 18000 and matches[0].get("number") is None
    no_journal = len(state["view"]["journals"]) == receipt["originalJournals"]
    recovered = None
    if report.get("qaProcessClosedGracefully") is False:
        # Guarded discarding of pending QA-only unsaved form; never kill.
        cmd = [sys.executable, "-B", str(ROOT / "scripts" /
               "qa_taraz_v106_safe_orphan_recovery_20261112.py"),
               "--report", str(report_file), "--discard-private"]
        completed = subprocess.run(cmd, cwd=ROOT, capture_output=True,
                                   text=True, timeout=35, check=False)
        try:
            recovered = json.loads(completed.stdout.strip())
        except (ValueError, TypeError):
            recovered = {"exitCode": completed.returncode, "errorType": "RecoveryOutputInvalid"}
        recovered["exitCode"] = completed.returncode
    output = {
        "qaExeSha256": report.get("exeSha"), "compiledSource": report.get("sourceSha"),
        "privateDesktop": report.get("privateDesktop"),
        "nativeUi": report.get("uia", {}).get("nativeQaDraft"),
        "expectedDraftPersisted": bool(exact), "journalCountUnchanged": bool(no_journal),
        "qaOnlyLedger": str(ledger), "installedUnchanged": report.get("baselineUnchanged"),
        "nativeCloseNormal": report.get("qaProcessClosedGracefully"),
        "gracefulOrphanRecovery": recovered,
        "report": str(report_file)
    }
    print(json.dumps(output, ensure_ascii=True))
    accepted = (bool(exact) and no_journal and
                report.get("baselineUnchanged") is True and
                report.get("priorTarazPidsPreserved") is True and
                report.get("uia", {}).get("nativeQaDraft", {}).get("saveInvoked") is True and
                (report.get("qaProcessClosedGracefully") is True or
                 isinstance(recovered, dict) and recovered.get("qaProcessClosedGracefully") is True))
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
