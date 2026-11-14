"""Use ONLY the genuine frozen Taraz.exe with a freshly-created synthetic book.

Experimental non-CDP/UI Automation harness. A click or SetValue is not proof
of React commit: independent SQLite replay is the sole persistence witness.
No user/backup data is copied. No real desktop/global input, process force kill,
installer, financial issue, bank access or operating MadarHost is touched.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import psutil
import re
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from standalone_accounting import StandaloneAccountingStore
from scripts import qa_taraz_v106_finalfix_native_gui_20261112 as qa
from scripts import qa_taraz_v103_native_gui_20261111 as native
from scripts import qa_taraz_v101_upgrade_acceptance_20261110 as acl

SOURCE_SHA = '73b692ca3b8790315a3c41be96960e059a06c6f9d6884cd8205edb1c2fe460c8'
BUILD_NAME = 'build-e13b4438f5d4'
EXE_SHA = '300dfff312dad2c5e5cc3984fc5afb39bc381857889989d4072ab83a34b592d3'
qa.BUILD = qa.ARTIFACTS / BUILD_NAME
qa.EXE = qa.BUILD / 'binary' / 'Taraz.exe'
qa.SOURCE_SHA = SOURCE_SHA
qa.EXE_SHA = EXE_SHA
OUTPUT = qa.ARTIFACTS / 'frozen-synthetic-private-uia-20261112'
CUSTOMER_ID = 'QA-FROZEN-ONLY-20261112'
ACCOUNTS = {'local': {'username': 'local', 'role': 'admin'}}

PROBE = r'''
 $out.syntheticOnly=$true
 $out.syntheticInventory=@{}
 foreach($label in @('مشتری حضوری','مشتری فاکتور','شرح ردیف 1',
   'تعداد ردیف 1','قیمت ردیف 1','یادداشت سند',
   'ذخیره پیش‌نویس فاکتور','ذخیره پیش‌فاکتور','بازگشت بدون ذخیره',
   'پیش‌فاکتور (پیشنهاد قیمت)','طراح قالب چاپ فاکتور')) {
  try {
   $elements=@(Named $label)
   $details=@()
   foreach($control in $elements){
    $value=$null;$invoke=$null;$select=$null
    $v=[bool]$control.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$value)
    $i=[bool]$control.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$invoke)
    $s=[bool]$control.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern,[ref]$select)
    $details+=@{type=[string]$control.Current.ControlType.ProgrammaticName;
      enabled=[bool]$control.Current.IsEnabled;valuePattern=$v;invokePattern=$i;
      selectionItemPattern=$s;value= $(if($v){[string]$value.Current.Value}else{''})}
   }
   $out.syntheticInventory[$label]=@($details)
  } catch { $out.syntheticInventory[$label]=@{error=$_.Exception.GetType().Name} }
 }
 $out.syntheticComboProbe=@{found=$false;expandPattern=$false;options=@()}
 $combos=@(Named 'مشتری فاکتور' | Where-Object {
   $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::ComboBox})
 if($combos.Count -eq 1){
  $out.syntheticComboProbe.found=$true
  $expand=$null
  if($combos[0].TryGetCurrentPattern(
    [System.Windows.Automation.ExpandCollapsePattern]::Pattern,[ref]$expand)){
    $out.syntheticComboProbe.expandPattern=$true
    try{$expand.Expand();Start-Sleep -Milliseconds 300}catch{}
  }
  $options=$combos[0].FindAll([System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)
  foreach($el in $options){
   $sel=$null
   $out.syntheticComboProbe.options+=@{
     name=[string]$el.Current.Name;
     type=[string]$el.Current.ControlType.ProgrammaticName;
     selectionItemPattern=[bool]$el.TryGetCurrentPattern(
       [System.Windows.Automation.SelectionItemPattern]::Pattern,[ref]$sel)}
  }
 }
'''

INVOICE = r'''
 $out.syntheticInvoiceUi=@{performed=$false;attemptedSave=$false;errors=@{};controls=@{}}
 if(-not $out.invoiceBeginnerOpened -or -not $out.invoiceBeginnerContentVisible){
   $out.syntheticInvoiceUi.errors.start='BEGINNER_NOT_AVAILABLE'
 } else {
  function ChangeValue([string]$label,[string]$value){
   for($retry=1;$retry -le 4;$retry++){
    $items=@(Named $label | Where-Object {$_.Current.IsEnabled -and
      $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit})
    if($items.Count -ne 1){$out.syntheticInvoiceUi.errors[$label]='COUNT_'+$items.Count;return $false}
    $pattern=$null
    if(-not $items[0].TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$pattern)){
      $out.syntheticInvoiceUi.errors[$label]='NO_VALUE_PATTERN';return $false
    }
    try {
      $pattern.SetValue($value)
      Start-Sleep -Milliseconds 350
      # React can remount a controlled input. Re-fetch its UIA element rather
      # than reading the stale ValuePattern object on the old element.
      $fresh=@(Named $label | Where-Object {$_.Current.IsEnabled -and
        $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit})
      $read=$null
      $match=($fresh.Count -eq 1 -and $fresh[0].TryGetCurrentPattern(
        [System.Windows.Automation.ValuePattern]::Pattern,[ref]$read) -and
        [string]$read.Current.Value -eq $value)
      $out.syntheticInvoiceUi.controls[$label]=@{uiaValueMatches=$match;attempts=$retry}
      if($match){return $true}
    } catch {$out.syntheticInvoiceUi.errors[$label]=$_.Exception.GetType().Name}
   }
   return $false
  }
  $customerInvoke=Activate 'مشتری حضوری'
  $out.syntheticInvoiceUi.customerClick=($customerInvoke -or
    [bool]$out.perNavigation['مشتری حضوری'].postedPrivateWin32)
  Start-Sleep -Milliseconds 350
  $a=ChangeValue 'شرح ردیف 1' 'QA FROZEN INVOICE LINE'
  $b=ChangeValue 'تعداد ردیف 1' '3'
  $c=ChangeValue 'قیمت ردیف 1' '4500'
  Start-Sleep -Milliseconds 700
  # Check all three surviving React-controlled values, not only SetValue's
  # immediate return. Never attempt the save on a partial form.
  foreach($entry in @(@('شرح ردیف 1','QA FROZEN INVOICE LINE'),
    @('تعداد ردیف 1','3'),@('قیمت ردیف 1','4500'))){
    $items=@(Named ([string]$entry[0]))
    $pattern=$null
    $ok=($items.Count -eq 1 -and $items[0].TryGetCurrentPattern(
      [System.Windows.Automation.ValuePattern]::Pattern,[ref]$pattern) -and
      [string]$pattern.Current.Value -eq [string]$entry[1])
    $out.syntheticInvoiceUi.controls[[string]$entry[0]].finalReadback=$ok
    if(-not $ok){$a=$false}
  }
  $save=@(Named 'ذخیره پیش‌نویس فاکتور' | Where-Object {
      $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button})
  $out.syntheticInvoiceUi.savePresent=($save.Count -eq 1)
  if($save.Count -eq 1){
   $out.syntheticInvoiceUi.saveEnabled=[bool]$save[0].Current.IsEnabled
  }
  if($a -and $b -and $c -and $out.syntheticInvoiceUi.customerClick -and
     $out.syntheticInvoiceUi.saveEnabled){
    $out.syntheticInvoiceUi.attemptedSave=$true
    $out.syntheticInvoiceUi.saveInvoked=Activate 'ذخیره پیش‌نویس فاکتور'
    Start-Sleep -Milliseconds 800
  }
  $out.syntheticInvoiceUi.performed=$true
 }
'''

PROFORMA = r'''
 $out.syntheticProformaUi=@{attemptedSave=$false;errors=@{};controls=@{}}
 function SetQuote([string]$label,[string]$value){
  $items=@(Named $label | Where-Object {$_.Current.IsEnabled -and
    $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit})
  if($items.Count -ne 1){$out.syntheticProformaUi.errors[$label]='COUNT_'+$items.Count;return $false}
  $valuePattern=$null
  if(-not $items[0].TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,
    [ref]$valuePattern)){return $false}
  try {$valuePattern.SetValue($value);Start-Sleep -Milliseconds 200
   $ok=([string]$valuePattern.Current.Value -eq $value)
   $out.syntheticProformaUi.controls[$label]=$ok;return $ok
  } catch {$out.syntheticProformaUi.errors[$label]=$_.Exception.GetType().Name;return $false}
 }
 $radio=@(Named 'پیش‌فاکتور (پیشنهاد قیمت)' | Where-Object {
   $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::RadioButton})
 if($radio.Count -eq 1){
  $selection=$null
  if($radio[0].TryGetCurrentPattern(
    [System.Windows.Automation.SelectionItemPattern]::Pattern,[ref]$selection)){
    try{$selection.Select();$out.syntheticProformaUi.radioSelected=$true}
    catch{$out.syntheticProformaUi.errors.radio=$_.Exception.GetType().Name}
  }
 }
 Start-Sleep -Milliseconds 350
 $customer=Activate 'مشتری حضوری'
 $out.syntheticProformaUi.customerSelected=($customer -or
   [bool]$out.perNavigation['مشتری حضوری'].postedPrivateWin32)
 Start-Sleep -Milliseconds 350
 $a=SetQuote 'شرح ردیف 1' 'QA FROZEN PROFORMA LINE'
 $b=SetQuote 'تعداد ردیف 1' '2'
 $c=SetQuote 'قیمت ردیف 1' '2500'
 Start-Sleep -Milliseconds 600
 $save=@(Named 'ذخیره پیش‌فاکتور' | Where-Object {
  $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button})
 $out.syntheticProformaUi.savePresent=($save.Count -eq 1)
 $out.syntheticProformaUi.saveEnabled=($save.Count -eq 1 -and $save[0].Current.IsEnabled)
 if($a -and $b -and $c -and $out.syntheticProformaUi.customerSelected -and
   $out.syntheticProformaUi.saveEnabled){
  $out.syntheticProformaUi.attemptedSave=$true
  $out.syntheticProformaUi.saveInvoked=Activate 'ذخیره پیش‌فاکتور'
  Start-Sleep -Milliseconds 900
 }
'''

EDIT_INVOICE = r'''
 $out.syntheticInvoiceEditUi=@{errors=@{};attemptedSave=$false}
 $out.syntheticInvoiceEditUi.back=Activate 'بازگشت بدون ذخیره'
 Start-Sleep -Milliseconds 450
 $out.syntheticInvoiceEditUi.edit=Activate 'ویرایش پیش‌نویس'
 Start-Sleep -Milliseconds 450
 $simple=Activate 'ساده و سریع'
 $out.syntheticInvoiceEditUi.simple=($simple -or
   [bool]$out.perNavigation['ساده و سریع'].postedPrivateWin32)
 Start-Sleep -Milliseconds 800
 function SetEditValue([string]$label,[string]$value){
  $items=@(Named $label | Where-Object {$_.Current.IsEnabled -and
   $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit})
  if($items.Count -ne 1){$out.syntheticInvoiceEditUi.errors[$label]='COUNT_'+$items.Count;return $false}
  $pattern=$null
  if(-not $items[0].TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,
    [ref]$pattern)){return $false}
  try{$pattern.SetValue($value);Start-Sleep -Milliseconds 250
    return ([string]$pattern.Current.Value -eq $value)}
  catch{$out.syntheticInvoiceEditUi.errors[$label]=$_.Exception.GetType().Name;return $false}
 }
 $a=SetEditValue 'تعداد ردیف 1' '4'
 $b=SetEditValue 'یادداشت سند' 'QA FROZEN EDIT AFTER REOPEN'
 Start-Sleep -Milliseconds 500
 $save=@(Named 'ذخیره پیش‌نویس فاکتور' | Where-Object {$_.Current.IsEnabled -and
   $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button})
 $out.syntheticInvoiceEditUi.saveEnabled=($save.Count -eq 1)
 if($a -and $b -and $out.syntheticInvoiceEditUi.edit -and
   $out.syntheticInvoiceEditUi.saveEnabled){
    $out.syntheticInvoiceEditUi.attemptedSave=$true
    $out.syntheticInvoiceEditUi.saveInvoked=Activate 'ذخیره پیش‌نویس فاکتور'
    Start-Sleep -Milliseconds 750
 }
'''

EDIT_PROFORMA = r'''
 $out.syntheticProformaEditUi=@{attemptedSave=$false;errors=@{}}
 $out.syntheticProformaEditUi.back=Activate 'بازگشت بدون ذخیره'
 Start-Sleep -Milliseconds 450
 $menu=Activate 'بازکردن فهرست بخش‌های تراز'
 $out.syntheticProformaEditUi.menu=($menu -or
   [bool]$out.perNavigation['بازکردن فهرست بخش‌های تراز'].postedPrivateWin32)
 Start-Sleep -Milliseconds 550
 $out.syntheticProformaEditUi.proformaTab=Activate 'پیش‌فاکتور مستقل'
 Start-Sleep -Milliseconds 550
 $out.syntheticProformaEditUi.edit=Activate 'ویرایش'
 Start-Sleep -Milliseconds 1200
 $out.syntheticProformaEditUi.beforeQuantityCount=@(Named 'تعداد').Count
 $out.syntheticProformaEditUi.beforeEditCapture=Capture 'proforma-before-quantity'
 function SetOfferValue([string]$name,[string]$value){
  for($attempt=1;$attempt -le 4;$attempt++){
   $items=@(Named $name | Where-Object {$_.Current.IsEnabled -and
    $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit})
   if($items.Count -ne 1){$out.syntheticProformaEditUi.errors[$name]='COUNT_'+$items.Count;return $false}
   $pattern=$null
   if(-not $items[0].TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,
    [ref]$pattern)){return $false}
   try {
    $pattern.SetValue($value)
    Start-Sleep -Milliseconds 350
    $fresh=@(Named $name | Where-Object {$_.Current.IsEnabled -and
      $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit})
    $read=$null
    if($fresh.Count -eq 1 -and $fresh[0].TryGetCurrentPattern(
      [System.Windows.Automation.ValuePattern]::Pattern,[ref]$read) -and
      [string]$read.Current.Value -eq $value){return $true}
   }catch{$out.syntheticProformaEditUi.errors[$name]=$_.Exception.GetType().Name}
  }
  return $false
 }
 # Change only one controlled field per React render. Writing another field
 # can re-mount the row and discard an uncommitted UIA value.
 $out.syntheticProformaEditUi.quantityChanged=SetOfferValue 'تعداد' '3'
 Start-Sleep -Milliseconds 750
 # The accessibility tree has BOTH a Text label and an Edit named 'تعداد'.
 # Only the editable input has a ValuePattern; counting the label as an input
 # incorrectly blocked a verified React value of '3'.
 $quantity=@(Named 'تعداد' | Where-Object {
   $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit})
 $out.syntheticProformaEditUi.afterQuantityCount=$quantity.Count
 $out.syntheticProformaEditUi.afterQuantityControls=@($quantity|ForEach-Object{
   @{type=[string]$_.Current.ControlType.ProgrammaticName;
     enabled=[bool]$_.Current.IsEnabled;
     value=$( $p=$null; if($_.TryGetCurrentPattern(
       [System.Windows.Automation.ValuePattern]::Pattern,[ref]$p)){
       [string]$p.Current.Value } else {''})}
 })
 $out.syntheticProformaEditUi.afterEditCapture=Capture 'proforma-after-quantity'
 $value=$null
 $out.syntheticProformaEditUi.quantitySurvived=($quantity.Count -eq 1 -and
   $quantity[0].TryGetCurrentPattern(
      [System.Windows.Automation.ValuePattern]::Pattern,[ref]$value) -and
   [string]$value.Current.Value -eq '3')
 if(-not $out.syntheticProformaEditUi.quantitySurvived -and $quantity.Count -eq 1){
   # UIA ValuePattern on React-controlled fields is not equivalent to
   # keyboard input. As a fallback send ONLY one concrete edit gesture
   # to the QA-owned Chrome_RenderWidgetHostHWND on the private desktop.
   # Never use SendInput or a global keyboard/desktop switch.
   $box=$quantity[0].Current.BoundingRectangle
   $out.syntheticProformaEditUi.targetedControlValidated=(
     $box.Width -gt 20 -and $box.Height -gt 12 -and
     $box.Width -lt 1400 -and $box.Height -lt 160)
   if($out.syntheticProformaEditUi.targetedControlValidated){
     $cx=[int][Math]::Round($box.X+$box.Width/2)
     $cy=[int][Math]::Round($box.Y+$box.Height/2)
     $found=New-Object 'System.Collections.Generic.List[System.IntPtr]'
     $cb=[TarazPrivateInput+Callback]{
       param($hwnd,$ignore)
       $owner=[uint32]0
       [void][TarazPrivateInput]::GetWindowThreadProcessId($hwnd,[ref]$owner)
       if($ids -notcontains [int]$owner){return $true}
       $cls=New-Object System.Text.StringBuilder 140
       [void][TarazPrivateInput]::GetClassName($hwnd,$cls,$cls.Capacity)
       if($cls.ToString() -notmatch '^Chrome_RenderWidgetHostHWND$'){return $true}
       $bounds=New-Object TarazPrivateInput+Rect
       if([TarazPrivateInput]::GetWindowRect($hwnd,[ref]$bounds) -and
          $cx -ge $bounds.L -and $cx -lt $bounds.R -and
          $cy -ge $bounds.T -and $cy -lt $bounds.B){$found.Add($hwnd)}
       return $true
     }
     [void][TarazPrivateInput]::EnumChildWindows(
       [IntPtr]$root.Current.NativeWindowHandle,$cb,[IntPtr]::Zero)
     $out.syntheticProformaEditUi.ownedRendererCount=$found.Count
     if($found.Count -eq 1){
       $target=$found[0]
       $point=New-Object TarazPrivateInput+Point
       $point.X=$cx;$point.Y=$cy
       if([TarazPrivateInput]::ScreenToClient($target,[ref]$point) -and
          $point.X -ge 0 -and $point.Y -ge 0 -and
          $point.X -lt 32767 -and $point.Y -lt 32767){
         $lp=[IntPtr]::new([int](($point.Y -shl 16) -bor $point.X))
         $clickDown=[TarazPrivateInput]::PostMessage(
           $target,[uint32]0x0201,[IntPtr]::new(1),$lp)
         $clickUp=[TarazPrivateInput]::PostMessage(
           $target,[uint32]0x0202,[IntPtr]::Zero,$lp)
         Start-Sleep -Milliseconds 200
         if($clickDown -and $clickUp){
           $messages=@(
             @([uint32]0x0100,[IntPtr]::new(0x11)), # Ctrl down
             @([uint32]0x0100,[IntPtr]::new(0x41)), # A down
             @([uint32]0x0101,[IntPtr]::new(0x41)), # A up
             @([uint32]0x0101,[IntPtr]::new(0x11)), # Ctrl up
             @([uint32]0x0100,[IntPtr]::new(0x33)), # 3 down
             @([uint32]0x0102,[IntPtr]::new(0x33)), # 3 char
             @([uint32]0x0101,[IntPtr]::new(0x33))  # 3 up
           )
           $posted=@($messages|ForEach-Object{
             [TarazPrivateInput]::PostMessage(
               $target,[uint32]$_[0],[IntPtr]$_[1],[IntPtr]::Zero)})
           $out.syntheticProformaEditUi.privateKeysPosted=($posted -notcontains $false)
           Start-Sleep -Milliseconds 700
           $again=@(Named 'تعداد' | Where-Object {
             $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit})
           $freshValue=$null
           if($again.Count -eq 1 -and $again[0].TryGetCurrentPattern(
              [System.Windows.Automation.ValuePattern]::Pattern,[ref]$freshValue)){
             $out.syntheticProformaEditUi.privateKeyReadback=[string]$freshValue.Current.Value
             $out.syntheticProformaEditUi.quantitySurvived=(
               [string]$freshValue.Current.Value -eq '3')
           }
         }
       }
     }
   }
 }
 $save=@(Named 'ثبت اصلاح' | Where-Object {$_.Current.IsEnabled -and
   $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button})
 $out.syntheticProformaEditUi.saveEnabled=($save.Count -eq 1)
 if($out.syntheticProformaEditUi.proformaTab -and
    $out.syntheticProformaEditUi.edit -and
    $out.syntheticProformaEditUi.quantityChanged -and
    $out.syntheticProformaEditUi.quantitySurvived -and
    $out.syntheticProformaEditUi.saveEnabled){
    $out.syntheticProformaEditUi.attemptedSave=$true
    $out.syntheticProformaEditUi.saveInvoked=Activate 'ثبت اصلاح'
    Start-Sleep -Milliseconds 1200
    $null=Capture 'proforma-after-save'
 }
'''

PRINT = r'''
 $out.syntheticPrintUi=@{errors=@{};attemptedSave=$false}
 $out.syntheticPrintUi.designerVisible=[bool]$out.printContentVisible
 $name=@(Named 'نام قالب' | Where-Object {$_.Current.IsEnabled -and
   $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit})
 $out.syntheticPrintUi.nameCount=$name.Count
 if($name.Count -eq 1){
  $valuePattern=$null
  if($name[0].TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,
    [ref]$valuePattern)){
    try {$valuePattern.SetValue('QA FROZEN PRIVATE PRINT TEMPLATE')
      Start-Sleep -Milliseconds 400
      $out.syntheticPrintUi.nameMatches=($valuePattern.Current.Value -eq
        'QA FROZEN PRIVATE PRINT TEMPLATE')
    } catch {$out.syntheticPrintUi.errors.name=$_.Exception.GetType().Name}
  }
 }
 $save=@(Named 'ذخیره قالب چاپ' | Where-Object {$_.Current.IsEnabled -and
   $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button})
 $out.syntheticPrintUi.saveEnabled=($save.Count -eq 1)
 if($out.syntheticPrintUi.nameMatches -and $out.syntheticPrintUi.saveEnabled){
  $out.syntheticPrintUi.attemptedSave=$true
  $out.syntheticPrintUi.saveInvoked=Activate 'ذخیره قالب چاپ'
  Start-Sleep -Milliseconds 600
 }
'''

PDF_INVOICE = r'''
 $out.syntheticPdfUi=@{attemptedDownload=$false;pdfEnabled=$false}
 $out.syntheticPdfUi.back=Activate 'بازگشت بدون ذخیره'
 Start-Sleep -Milliseconds 850
 $pdf=@(Named 'PDF' | Where-Object {
   $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and
   $_.Current.IsEnabled})
 $out.syntheticPdfUi.pdfButtonCount=$pdf.Count
 $out.syntheticPdfUi.pdfEnabled=($pdf.Count -eq 1)
 if($out.syntheticPdfUi.back -and $out.syntheticPdfUi.pdfEnabled){
    $out.syntheticPdfUi.attemptedDownload=$true
    $out.syntheticPdfUi.downloadInvoked=Activate 'PDF'
    Start-Sleep -Milliseconds 1200
    # Capture only QA-owned OS dialogs, never inspect user desktop dialogs.
    $desktopWindows=[System.Windows.Automation.AutomationElement]::RootElement.FindAll(
      [System.Windows.Automation.TreeScope]::Children,
      [System.Windows.Automation.Condition]::TrueCondition)
    $dialogs=@($desktopWindows|Where-Object {
      $ids -contains [int]$_.Current.ProcessId -and
      $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Window -and
      $_.Current.Name -ne 'تراز | حسابداری'
    })
    $out.syntheticPdfUi.dialogs=@($dialogs|ForEach-Object{
      @{name=[string]$_.Current.Name;pid=[int]$_.Current.ProcessId;
        class=[string]$_.Current.ClassName}
    })
    foreach($dialog in $dialogs){
      $children=$dialog.FindAll([System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition)
      $out.syntheticPdfUi.dialogControls=@(
        $children|Where-Object{
          $_.Current.ControlType -in @(
            [System.Windows.Automation.ControlType]::Edit,
            [System.Windows.Automation.ControlType]::Button)
        }|Select-Object -First 45|ForEach-Object{
          @{name=[string]$_.Current.Name;
            type=[string]$_.Current.ControlType.ProgrammaticName;
            enabled=[bool]$_.Current.IsEnabled;
            id=[string]$_.Current.AutomationId}
        })
    }
 }
'''

ORDERS_CREATE = r'''
 $out.syntheticOrderCreateUi=@{attemptedSave=$false;errors=@{};controls=@{}}
 $out.syntheticOrderCreateUi.back=Activate 'بازگشت بدون ذخیره'
 Start-Sleep -Milliseconds 350
 $out.syntheticOrderCreateUi.nav=Activate 'سفارش‌ها'
 Start-Sleep -Milliseconds 1100
 if(-not(Has @('نام مشتری','شرح سفارش'))){Start-Sleep -Milliseconds 900}
 if(-not(Has @('نام مشتری','شرح سفارش'))){
    $menu=Activate 'بازکردن فهرست بخش‌های تراز'
    Start-Sleep -Milliseconds 250
    $null=Activate 'سفارش‌ها'
    Start-Sleep -Milliseconds 750
 }
 $out.syntheticOrderCreateUi.editorReady=Has @('نام مشتری','شرح سفارش')
 if($out.syntheticOrderCreateUi.editorReady){
  function OrderValue([string]$name,[string]$value){
   for($attempt=1;$attempt -le 4;$attempt++){
    $items=@(Named $name|Where-Object{$_.Current.IsEnabled -and
       $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit})
    if($items.Count -ne 1){$out.syntheticOrderCreateUi.errors[$name]='COUNT_'+$items.Count;return $false}
    $pat=$null
    if(-not $items[0].TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,
      [ref]$pat)){return $false}
    try {
      $pat.SetValue($value)
      Start-Sleep -Milliseconds 300
      $fresh=@(Named $name|Where-Object{$_.Current.IsEnabled -and
         $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit})
      $read=$null
      if($fresh.Count -eq 1 -and $fresh[0].TryGetCurrentPattern(
         [System.Windows.Automation.ValuePattern]::Pattern,[ref]$read) -and
         [string]$read.Current.Value -eq $value){
        $out.syntheticOrderCreateUi.controls[$name]=$true;return $true
      }
    }catch{$out.syntheticOrderCreateUi.errors[$name]=$_.Exception.GetType().Name}
   }
   $out.syntheticOrderCreateUi.controls[$name]=$false
   return $false
  }
  Start-Sleep -Milliseconds 500
  $valid=@()
  $valid+=OrderValue 'نام مشتری' 'QA FROZEN ORDER CUSTOMER'
  $valid+=OrderValue 'شرح سفارش' 'QA FROZEN ORDER TEXT'
  $valid+=OrderValue 'تعداد سفارش' '100'
  $valid+=OrderValue 'تعداد برنامه‌ریزی تولید' '120'
  $valid+=OrderValue 'قیمت واحد (اختیاری، ریال)' '25000'
  $out.syntheticOrderCreateUi.stageAdded=Activate 'افزودن مرحله'
  Start-Sleep -Milliseconds 450
  $valid+=OrderValue 'هزینه مرحله 1' '200000'
  Start-Sleep -Milliseconds 600
  $out.syntheticOrderCreateUi.allFieldsSet=($valid -notcontains $false)
  $save=@(Named 'ذخیره سفارش'|Where-Object {$_.Current.IsEnabled -and
     $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button})
  $out.syntheticOrderCreateUi.saveEnabled=($save.Count -eq 1)
  if($out.syntheticOrderCreateUi.allFieldsSet -and
     $out.syntheticOrderCreateUi.stageAdded -and
     $out.syntheticOrderCreateUi.saveEnabled){
    $out.syntheticOrderCreateUi.attemptedSave=$true
    $out.syntheticOrderCreateUi.saveInvoked=Activate 'ذخیره سفارش'
    Start-Sleep -Milliseconds 1000
  }
 }
'''

ORDERS_COST = r'''
 $out.syntheticOrderCostUi=@{attemptedRecord=$false;errors=@{}}
 $out.syntheticOrderCostUi.back=Activate 'بازگشت بدون ذخیره'
 Start-Sleep -Milliseconds 350
 $out.syntheticOrderCostUi.menu=Activate 'بازکردن فهرست بخش‌های تراز'
 Start-Sleep -Milliseconds 500
 $out.syntheticOrderCostUi.nav=Activate 'سفارش‌ها'
 Start-Sleep -Milliseconds 1100
 if(-not(Has @('ویرایش / مشاهده'))){
  Start-Sleep -Milliseconds 750
 }
 $out.syntheticOrderCostUi.selected=Activate 'ویرایش / مشاهده'
 Start-Sleep -Milliseconds 900
 function CostValue([string]$name,[string]$value){
  $items=@(Named $name | Where-Object {$_.Current.IsEnabled -and
    $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit})
  if($items.Count -ne 1){$out.syntheticOrderCostUi.errors[$name]='COUNT_'+$items.Count;return $false}
  $pattern=$null
  if(-not $items[0].TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,
    [ref]$pattern)){return $false}
  try{$pattern.SetValue($value);Start-Sleep -Milliseconds 500
   $fresh=@(Named $name)
   $p=$null
   if($fresh.Count -eq 1 -and $fresh[0].TryGetCurrentPattern(
      [System.Windows.Automation.ValuePattern]::Pattern,[ref]$p)){
     $actual=[string]$p.Current.Value
     $out.syntheticOrderCostUi[$name+'Value']=$actual
     return $actual -eq $value -or ($name -like 'تاریخ هزینه*' -and
       $actual -in @('11/14/2026','14/11/2026'))
   }
  }catch{$out.syntheticOrderCostUi.errors[$name]=$_.Exception.GetType().Name}
  return $false
 }
 $out.syntheticOrderCostUi.costSet=CostValue 'هزینه واقعی مرحله 1' '180000'
 $out.syntheticOrderCostUi.todayShortcut=Activate 'انتخاب تاریخ امروز برای هزینه مرحله 1'
 Start-Sleep -Milliseconds 450
 $todayField=@(Named 'تاریخ هزینه مرحله 1')
 $todayPattern=$null
 $out.syntheticOrderCostUi.dateSet=($todayField.Count -eq 1 -and
   $todayField[0].TryGetCurrentPattern(
     [System.Windows.Automation.ValuePattern]::Pattern,[ref]$todayPattern) -and
   [string]$todayPattern.Current.Value -in @('2026-11-14','11/14/2026','14/11/2026'))
 $out.syntheticOrderCostUi.todayShortcutReadback=if($todayPattern){
   [string]$todayPattern.Current.Value}else{''}
 if(-not $out.syntheticOrderCostUi.dateSet){
   $out.syntheticOrderCostUi.dateSet=CostValue 'تاریخ هزینه مرحله 1' '2026-11-14'
 }
 if(-not $out.syntheticOrderCostUi.dateSet){
    $date=@(Named 'تاریخ هزینه مرحله 1')
    if($date.Count -eq 1){
       $child=$date[0].FindAll([System.Windows.Automation.TreeScope]::Descendants,
         [System.Windows.Automation.Condition]::TrueCondition)
       $picker=@($child|Where-Object{$_.Current.Name -like 'Show date picker*'})
       $out.syntheticOrderCostUi.earlyPickerCount=$picker.Count
       if($picker.Count -eq 1){
         $expand=$null
         if($picker[0].TryGetCurrentPattern(
           [System.Windows.Automation.ExpandCollapsePattern]::Pattern,[ref]$expand)){
           try{
              $expand.Expand()
              Start-Sleep -Milliseconds 350
              $out.syntheticOrderCostUi.earlyPickerExpanded=$true
              $options=[System.Windows.Automation.AutomationElement]::RootElement.FindAll(
                [System.Windows.Automation.TreeScope]::Descendants,
                [System.Windows.Automation.Condition]::TrueCondition)
              $out.syntheticOrderCostUi.earlyPickerOptions=@(
                 $options|Where-Object{
                   ($ids -contains [int]$_.Current.ProcessId) -and
                   $_.Current.Name -match 'Today|14|Nov|2026|امروز|تقویم'
                 }|Select-Object -First 55|ForEach-Object{
                   @{name=[string]$_.Current.Name;
                     type=[string]$_.Current.ControlType.ProgrammaticName;
                     enabled=[bool]$_.Current.IsEnabled}
                 })
              $today=@($options|Where-Object{
                 ($ids -contains [int]$_.Current.ProcessId) -and
                 $_.Current.Name -eq 'Today' -and
                 $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and
                 $_.Current.IsEnabled})
              $out.syntheticOrderCostUi.todayCount=$today.Count
              if($today.Count -eq 1){
                 $action=Activate 'Today'
                 $out.syntheticOrderCostUi.todayAction=($action -or
                    [bool]$out.perNavigation['Today'].postedPrivateWin32)
                 Start-Sleep -Milliseconds 450
                 $latest=@(Named 'تاریخ هزینه مرحله 1')
                 $read=$null
                 if($latest.Count -eq 1 -and $latest[0].TryGetCurrentPattern(
                     [System.Windows.Automation.ValuePattern]::Pattern,[ref]$read)){
                    $out.syntheticOrderCostUi.todayReadback=[string]$read.Current.Value
                    $out.syntheticOrderCostUi.dateSet=($out.syntheticOrderCostUi.todayReadback -in
                      @('2026-11-14','11/14/2026','14/11/2026'))
                 }
              }
              if(-not $out.syntheticOrderCostUi.dateSet){
              $chosen=@($options|Where-Object{
                ($ids -contains [int]$_.Current.ProcessId) -and
                $_.Current.Name -eq 'Saturday, November 14, 2026' -and
                $_.Current.IsEnabled -and
                $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::DataItem})
              $out.syntheticOrderCostUi.dayCellCount=$chosen.Count
              if($chosen.Count -eq 1){
                $out.syntheticOrderCostUi.dayCellPatterns=@(
                  $chosen[0].GetSupportedPatterns()|ForEach-Object{$_.ProgrammaticName})
                $invoke=$null;$select=$null
                if($chosen[0].TryGetCurrentPattern(
                  [System.Windows.Automation.InvokePattern]::Pattern,[ref]$invoke)){
                    try{$invoke.Invoke();$out.syntheticOrderCostUi.dayCellInvoked=$true}
                    catch{$out.syntheticOrderCostUi.dayCellError=$_.Exception.GetType().Name}
                }elseif($chosen[0].TryGetCurrentPattern(
                  [System.Windows.Automation.SelectionItemPattern]::Pattern,[ref]$select)){
                    try{$select.Select();$out.syntheticOrderCostUi.dayCellSelected=$true}
                    catch{$out.syntheticOrderCostUi.dayCellError=$_.Exception.GetType().Name}
                }
                Start-Sleep -Milliseconds 450
                $current=@(Named 'تاریخ هزینه مرحله 1')
                $read=$null
                if($current.Count -eq 1 -and $current[0].TryGetCurrentPattern(
                    [System.Windows.Automation.ValuePattern]::Pattern,[ref]$read)){
                   $out.syntheticOrderCostUi.calendarReadback=[string]$read.Current.Value
                   $out.syntheticOrderCostUi.dateSet=(
                      $out.syntheticOrderCostUi.calendarReadback -in
                       @('2026-11-14','11/14/2026','14/11/2026'))
                }
              }
              }
           }catch{$out.syntheticOrderCostUi.earlyPickerError=$_.Exception.GetType().Name}
         }
       }
    }
 }
 if(-not $out.syntheticOrderCostUi.dateSet){
   $date=@(Named 'تاریخ هزینه مرحله 1'|Where-Object{
     $_.Current.IsEnabled -and
     $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit})
   $out.syntheticOrderCostUi.dateInputCount=$date.Count
   if($date.Count -eq 1){
     $out.syntheticOrderCostUi.dateSupportedPatterns=@(
       $date[0].GetSupportedPatterns()|ForEach-Object{$_.ProgrammaticName})
     $out.syntheticOrderCostUi.dateChildren=@(
       $date[0].FindAll([System.Windows.Automation.TreeScope]::Descendants,
         [System.Windows.Automation.Condition]::TrueCondition) |
       Select-Object -First 12 | ForEach-Object{
         @{name=[string]$_.Current.Name;
           type=[string]$_.Current.ControlType.ProgrammaticName;
           patterns=@($_.GetSupportedPatterns()|ForEach-Object{$_.ProgrammaticName})}
       })
     try{
       $date[0].SetFocus()
       $out.syntheticOrderCostUi.dateFocusAttempted=$true
       $out.syntheticOrderCostUi.dateSetAfterFocus=CostValue 'تاریخ هزینه مرحله 1' '2026-11-14'
       if($out.syntheticOrderCostUi.dateSetAfterFocus){
         $out.syntheticOrderCostUi.dateSet=$true
       }
     }catch{$out.syntheticOrderCostUi.dateFocusError=$_.Exception.GetType().Name}
     if(-not $out.syntheticOrderCostUi.dateSet){
       $out.syntheticOrderCostUi.segmentResults=@{}
       $segments=$date[0].FindAll([System.Windows.Automation.TreeScope]::Descendants,
         [System.Windows.Automation.Condition]::TrueCondition)
       foreach($segment in @(@('Month',11),@('Day',14),@('Year',2026))){
         $name=[string]$segment[0]
         $number=[double]$segment[1]
         $candidates=@($segments|Where-Object{
           $_.Current.Name -eq ($name+' تاریخ هزینه مرحله 1') -and
           $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Spinner})
         $segmentResult=@{found=$candidates.Count;set=$false}
         if($candidates.Count -eq 1){
           $range=$null
           if($candidates[0].TryGetCurrentPattern(
             [System.Windows.Automation.RangeValuePattern]::Pattern,[ref]$range)){
             $segmentResult.rangeBefore=[double]$range.Current.Value
             $segmentResult.rangeReadOnly=[bool]$range.Current.IsReadOnly
             try{
               if(-not $range.Current.IsReadOnly){
                 $range.SetValue($number)
                 Start-Sleep -Milliseconds 270
                 $segmentResult.rangeAfter=[double]$range.Current.Value
                 $segmentResult.set=($segmentResult.rangeAfter -eq $number)
               }
             }catch{$segmentResult.rangeError=$_.Exception.GetType().Name}
           }
           if(-not $segmentResult.set){
             $v=$null
             if($candidates[0].TryGetCurrentPattern(
                [System.Windows.Automation.ValuePattern]::Pattern,[ref]$v)){
                try{
                  $v.SetValue([string][int]$number)
                  Start-Sleep -Milliseconds 240
                  $segmentResult.valueAfter=[string]$v.Current.Value
                  $segmentResult.set=($segmentResult.valueAfter -eq [string][int]$number)
                }catch{$segmentResult.valueError=$_.Exception.GetType().Name}
             }
           }
         }
         $out.syntheticOrderCostUi.segmentResults[$name]=$segmentResult
       }
       Start-Sleep -Milliseconds 300
       $recheck=@(Named 'تاریخ هزینه مرحله 1')
       $vp=$null
       if($recheck.Count -eq 1 -and $recheck[0].TryGetCurrentPattern(
          [System.Windows.Automation.ValuePattern]::Pattern,[ref]$vp)){
          $out.syntheticOrderCostUi.dateAfterSegments=[string]$vp.Current.Value
          $out.syntheticOrderCostUi.dateSet=($out.syntheticOrderCostUi.dateAfterSegments -in
            @('2026-11-14','11/14/2026','14/11/2026'))
       }
     }
     $legacy=$null
     $out.syntheticOrderCostUi.dateLegacyPattern=[bool]$date[0].TryGetCurrentPattern(
       [System.Windows.Automation.LegacyIAccessiblePattern]::Pattern,[ref]$legacy)
     if($out.syntheticOrderCostUi.dateLegacyPattern){
       try{
         $out.syntheticOrderCostUi.legacyValueBefore=[string]$legacy.Current.Value
         $legacy.SetValue('11/14/2026')
         Start-Sleep -Milliseconds 600
         $new=@(Named 'تاریخ هزینه مرحله 1')
         $p=$null
         if($new.Count -eq 1 -and $new[0].TryGetCurrentPattern(
             [System.Windows.Automation.ValuePattern]::Pattern,[ref]$p)){
           $out.syntheticOrderCostUi.dateLegacyValueAfter=[string]$p.Current.Value
           $out.syntheticOrderCostUi.dateSet=([string]$p.Current.Value -in
             @('2026-11-14','11/14/2026','14/11/2026'))
         }
       }catch{$out.syntheticOrderCostUi.legacyError=$_.Exception.GetType().Name}
     }
   }
 }
 if(-not $out.syntheticOrderCostUi.dateSet){
   foreach($candidate in @('11/14/2026','14/11/2026','November 14, 2026')){
     if(CostValue 'تاریخ هزینه مرحله 1' $candidate){
       $out.syntheticOrderCostUi.dateSet=$true
       $out.syntheticOrderCostUi.dateInputAccepted=$candidate
       break
     }
   }
 }
 if(-not $out.syntheticOrderCostUi.dateSet){
   $date=@(Named 'تاریخ هزینه مرحله 1')
   if($date.Count -eq 1){
     $picker=$date[0].FindAll([System.Windows.Automation.TreeScope]::Descendants,
       [System.Windows.Automation.Condition]::TrueCondition)
     $controls=@($picker|Where-Object{$_.Current.Name -like 'Show date picker*'})
     $out.syntheticOrderCostUi.pickerControlCount=$controls.Count
     if($controls.Count -eq 1){
       $expand=$null
       if($controls[0].TryGetCurrentPattern(
         [System.Windows.Automation.ExpandCollapsePattern]::Pattern,[ref]$expand)){
          try{
             $expand.Expand()
             $out.syntheticOrderCostUi.pickerExpanded=$true
             Start-Sleep -Milliseconds 450
             $visible=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
               [System.Windows.Automation.Condition]::TrueCondition)
             $out.syntheticOrderCostUi.pickerNames=@(
               $visible|Where-Object{$_.Current.Name -match 'Today|14|Nov|2026|امروز|تقویم' } |
               Select-Object -First 90|ForEach-Object{
                 @{name=[string]$_.Current.Name;type=[string]$_.Current.ControlType.ProgrammaticName}
               })
          }catch{$out.syntheticOrderCostUi.pickerError=$_.Exception.GetType().Name}
       }
     }
   }
 }
 Start-Sleep -Milliseconds 450
 $record=@(Named 'ثبت هزینه واقعی'|Where-Object {$_.Current.IsEnabled -and
   $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button})
 $out.syntheticOrderCostUi.recordEnabled=($record.Count -eq 1)
 if($out.syntheticOrderCostUi.selected -and $out.syntheticOrderCostUi.costSet -and
    $out.syntheticOrderCostUi.dateSet -and $out.syntheticOrderCostUi.recordEnabled){
    $out.syntheticOrderCostUi.attemptedRecord=$true
    $out.syntheticOrderCostUi.recordInvoked=Activate 'ثبت هزینه واقعی'
    Start-Sleep -Milliseconds 1100
 }
'''

ORDERS_PAYMENT = r'''
 $out.syntheticOrderPaymentUi=@{attemptedSave=$false;errors=@{};controls=@{}}
 $out.syntheticOrderPaymentUi.back=Activate 'بازگشت بدون ذخیره'
 Start-Sleep -Milliseconds 400
 $out.syntheticOrderPaymentUi.menu=Activate 'بازکردن فهرست بخش‌های تراز'
 Start-Sleep -Milliseconds 400
 $out.syntheticOrderPaymentUi.nav=Activate 'سفارش‌ها'
 Start-Sleep -Milliseconds 950
 $out.syntheticOrderPaymentUi.select=Activate 'ویرایش / مشاهده'
 Start-Sleep -Milliseconds 750
 function SetPay([string]$name,[string]$value){
  for($i=1;$i -le 4;$i++){
   $a=@(Named $name | Where-Object {$_.Current.IsEnabled -and
      $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit})
   if($a.Count -ne 1){$out.syntheticOrderPaymentUi.errors[$name]='COUNT_'+$a.Count;return $false}
   $v=$null
   if(-not $a[0].TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$v)){
      return $false
   }
   try{
    $v.SetValue($value)
    Start-Sleep -Milliseconds 350
    $fresh=@(Named $name)
    $read=$null
    if($fresh.Count -eq 1 -and $fresh[0].TryGetCurrentPattern(
      [System.Windows.Automation.ValuePattern]::Pattern,[ref]$read) -and
      [string]$read.Current.Value -eq $value){
      $out.syntheticOrderPaymentUi.controls[$name]=$true;return $true
    }
   }catch{$out.syntheticOrderPaymentUi.errors[$name]=$_.Exception.GetType().Name}
  }
  return $false
 }
 $out.syntheticOrderPaymentUi.amount=SetPay 'مبلغ پرداخت سفارش' '500000'
 $out.syntheticOrderPaymentUi.method=SetPay 'روش پرداخت سفارش' 'bank-transfer'
 $date=@(Named 'تاریخ پرداخت سفارش')
 $out.syntheticOrderPaymentUi.dateControlPresent=($date.Count -eq 1)
 $party=@(Named 'طرف حساب پرداخت سفارش')
 $out.syntheticOrderPaymentUi.partyPresent=($party.Count -eq 1)
 $ready=@(Named 'ثبت در پرونده سفارش (نه بانک)' | Where-Object {
    $_.Current.IsEnabled -and
    $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button})
 $out.syntheticOrderPaymentUi.saveEnabled=($ready.Count -eq 1)
 if($out.syntheticOrderPaymentUi.select -and
    $out.syntheticOrderPaymentUi.amount -and
    $out.syntheticOrderPaymentUi.method -and
    $out.syntheticOrderPaymentUi.dateControlPresent -and
    $out.syntheticOrderPaymentUi.partyPresent -and
    $out.syntheticOrderPaymentUi.saveEnabled){
    $out.syntheticOrderPaymentUi.attemptedSave=$true
    $out.syntheticOrderPaymentUi.saveInvoked=Activate 'ثبت در پرونده سفارش (نه بانک)'
    Start-Sleep -Milliseconds 1150
 }
'''

OWNED_CLOSE_CONFIRM = r'''
param([string]$OwnerIds,[string]$ResultFile)
$ErrorActionPreference='Stop'
$pids=@($OwnerIds.Split(',')|ForEach-Object{[int]$_})
$out=@{status='NOT_OBSERVED';syntheticDiscardConfirmed=$false;
       noGlobalInput=$true;noForceTermination=$true}
try{
 Add-Type -AssemblyName UIAutomationClient
 Add-Type -AssemblyName UIAutomationTypes
 $windows=[System.Windows.Automation.AutomationElement]::RootElement.FindAll(
   [System.Windows.Automation.TreeScope]::Children,
   [System.Windows.Automation.Condition]::TrueCondition)
 $own=@($windows|Where-Object{$pids -contains [int]$_.Current.ProcessId -and
   $_.Current.Name -eq 'تراز | حسابداری'})
 if($own.Count -ne 1){throw 'Not exactly one owned Taraz window'}
 $desc=$own[0].FindAll([System.Windows.Automation.TreeScope]::Descendants,
   [System.Windows.Automation.Condition]::TrueCondition)
 $expected='اطلاعات این فرم حسابداری هنوز ذخیره نشده است. پنجره را ببندیم و تغییرات را کنار بگذاریم؟'
 $msg=@($desc|Where-Object{$pids -contains [int]$_.Current.ProcessId -and
    $_.Current.Name -eq $expected -and
    $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Text})
 $btn=@($desc|Where-Object{$pids -contains [int]$_.Current.ProcessId -and
    $_.Current.Name -eq 'OK' -and $_.Current.IsEnabled -and
    $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button})
 if($msg.Count -eq 1 -and $btn.Count -eq 1){
    $pattern=$null
    if($btn[0].TryGetCurrentPattern(
        [System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)){
       $pattern.Invoke()
       $out.syntheticDiscardConfirmed=$true
    }
 }
 $out.status='PRIVATE_CONFIRM_INSPECTED'
}catch{$out.status='PRIVATE_CONFIRM_ERROR';$out.errorType=$_.Exception.GetType().Name}
[IO.File]::WriteAllText($ResultFile,($out|ConvertTo-Json -Compress),
  [Text.UTF8Encoding]::new($false))
'''


def settle_private_close(desktop, owner_pids, work, env):
    """Only click the exact unsaved-draft discard confirmation, if present."""
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    script = work / 'private-profile' / 'owned-close-confirm.ps1'
    report = work / 'private-profile' / 'owned-close-confirm.json'
    script.write_text(OWNED_CLOSE_CONFIRM, encoding='utf-8-sig')
    pid, handle, thread = desktop.spawn(powershell, work, env, (
        '-NoProfile','-NonInteractive','-WindowStyle','Hidden',
        '-ExecutionPolicy','Bypass','-File',str(script),
        '-OwnerIds',','.join(str(x) for x in sorted(owner_pids)),
        '-ResultFile',str(report)))
    try:
        if ctypes.windll.kernel32.WaitForSingleObject(handle, 12000) != 0:
            return {'status':'PRIVATE_CONFIRM_HELPER_TIMEOUT_NO_TERMINATION'}
        if not report.is_file():
            return {'status':'PRIVATE_CONFIRM_REPORT_MISSING'}
        return json.loads(report.read_text(encoding='utf-8-sig'))
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
        ctypes.windll.kernel32.CloseHandle(thread)


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def private_download_directory(work):
    """Set the standard Chromium preference solely in QA-owned WebView2 data."""
    target=work/'private-downloads'
    target.mkdir(exist_ok=True)
    if target.is_symlink():
        raise PermissionError('Refusing linked QA download destination')
    prefs=work/'private-profile'/'qa'/'qa-runtime'/'webview-profile'/'EBWebView'/'Default'/'Preferences'
    if prefs.is_file():
        data=json.loads(prefs.read_text(encoding='utf-8'))
        download=data.setdefault('download',{})
        download['default_directory']=str(target.resolve())
        download['prompt_for_download']=False
        download['directory_upgrade']=True
        prefs.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),
                         encoding='utf-8')
    return target


def pdf_integrity(path):
    """Validate the single-page raster PDF's JPEG content without OCR."""
    from PIL import Image,ImageStat
    payload=Path(path).read_bytes()
    pages=len(re.findall(rb'/Type\s*/Page\b',payload))
    jpegs=re.findall(rb'\bstream\r?\n(.*?)\r?\nendstream',payload,re.S)
    samples=[]
    for stream in jpegs:
        if not stream.startswith(b'\xff\xd8'):
            continue
        with Image.open(io.BytesIO(stream)) as pic:
            image=pic.convert('RGB')
            stat=ImageStat.Stat(image)
            samples.append({'width':image.width,'height':image.height,
                            'variance':round(sum(stat.var),2)})
    return {'headerValid':payload.startswith(b'%PDF-1.4'),
            'hasEof':b'%%EOF' in payload[-100:],
            'pageCount':pages,'jpegPageCount':len(samples),
            'images':samples,'bytes':len(payload),'sha256':sha(path),
            'renderedContentNonblank':bool(samples and all(
                entry['variance']>150 for entry in samples))}


def owned_uia_long_wait(desktop,pids,work,env):
    """One exact private window; wait for QA UIA to finish, no forced kill."""
    powershell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    uid=uuid.uuid4().hex[:10]
    script=work/'private-profile'/('owned-uia-'+uid+'.ps1')
    output=work/'private-profile'/('owned-uia-'+uid+'.json')
    script.write_text(qa.PRIVATE_UIA,encoding='utf-8-sig')
    pid,handle,thread=desktop.spawn(powershell,work,env,
        ('-NoProfile','-NonInteractive','-WindowStyle','Hidden',
         '-ExecutionPolicy','Bypass','-File',str(script),
         '-OwnerIds',','.join(map(str,sorted(pids))),
         '-ResultFile',str(output),'-ScreenshotFolder',str(work/'private-profile')))
    try:
        if ctypes.windll.kernel32.WaitForSingleObject(handle,80000)!=0:
            return {'status':'PRIVATE_UIA_TIMEOUT_NO_TERMINATION',
                    'helperProcessMayRemain':True}
        if not output.is_file():
            return {'status':'PRIVATE_UIA_REPORT_MISSING'}
        return json.loads(output.read_text(encoding='utf-8-sig'))
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
        ctypes.windll.kernel32.CloseHandle(thread)


def synthetic_paths(work: Path):
    runtime=work/'private-profile'/'qa'/'qa-runtime'
    roots={'roaming': runtime/'roaming'/'Taraz',
           'local': runtime/'localappdata'/'Taraz',
           'bridge':runtime/'localappdata'/'Madar-Taraz-Bridge'}
    for part in roots.values():
        part.mkdir(parents=True,exist_ok=True)
    return runtime,roots


def seed_new_book(roots):
    book=StandaloneAccountingStore(roots['roaming']/'standalone-accounting.sqlite3',
                                   default_currency='RIAL')
    result=book.command({
        'type':'party.register','eventId':'QA-FROZEN-PARTY-20261112',
        'partyId':CUSTOMER_ID,'name':'مشتری حضوری','kind':'customer',
    },actor='local',accounts=ACCOUNTS,expected_revision=0,
       now=datetime.now(timezone.utc).isoformat())
    if result['revision']!=1 or result['view']['journals']:
        raise RuntimeError('Synthetic ledger initialization was not isolated')


def book_witness(roots):
    from standalone_accounting_template_store import StandaloneAccountingTemplateStore
    from taraz_order_store import TarazOrderStore
    book=StandaloneAccountingStore(roots['roaming']/'standalone-accounting.sqlite3',
                                   default_currency='RIAL')
    result=book.read(actor='local',accounts=ACCOUNTS)
    view=result['view']
    templates=StandaloneAccountingTemplateStore(roots['roaming']).list('print')['templates']
    orders=TarazOrderStore(roots['roaming']).list(offset=0,limit=100)
    return {'revision':result['revision'],'invoiceCount':len(view['invoices']),
            'proformaCount':len(view['proformas']),'journalCount':len(view['journals']),
            'partyCount':len(view['parties']),
            'printTemplateCount':len(templates),
            'printTemplateTitles':[entry['title'] for entry in templates],
            'orderCount':orders['total'],
            'orders':[{'id':o['id'],'revision':o['revision'],'quantity':o['quantity'],
                       'productionQuantity':o['productionQuantity'],
                       'costStageCount':len(o['costStages']),
                       'costRecords':o.get('costRecords',[]),'payments':o.get('payments',[]),
                       'recordedActualCostTotal':o.get('recordedActualCostTotal'),
                       'financialEventCreated':o.get('financialEventCreated')}
                      for o in orders['orders']],
            'invoices':[{'id':d['id'],'total':d['total'],'status':d['status'],
                         'createdBy':d.get('createdBy'),'createdAt':bool(d.get('createdAt')),
                         'editedBy':d.get('editedBy'),'editedAt':bool(d.get('editedAt'))}
                        for d in view['invoices'].values()],
            'proformas':[{'id':d['id'],'total':d['total'],'status':d['status'],
                          'createdBy':d.get('createdBy'),'createdAt':bool(d.get('createdAt')),
                          'editedBy':d.get('editedBy'),'editedAt':bool(d.get('editedAt'))}
                         for d in view['proformas'].values()]}


def phase_persisted(phase, witness, downloads=None):
    """Evaluate only the requested stage; fresh synthetic books can be empty."""
    if phase == 'invoice':
        return witness['invoiceCount'] == 1
    if phase == 'proforma':
        return witness['proformaCount'] == 1
    if phase == 'invoice-edit':
        return bool(witness['invoices'] and witness['invoices'][0]['total']==18000)
    if phase == 'proforma-edit':
        return bool(witness['proformas'] and witness['proformas'][0]['total']==7500)
    if phase == 'print':
        return 'QA FROZEN PRIVATE PRINT TEMPLATE' in witness['printTemplateTitles']
    if phase == 'order-create':
        return witness['orderCount']==1
    if phase == 'order-cost':
        return bool(witness['orders'] and witness['orders'][0]['costRecords'])
    if phase == 'order-payment':
        return bool(witness['orders'] and witness['orders'][0]['payments'])
    if phase == 'pdf-invoice':
        return downloads is not None and bool(list(downloads.glob('*.pdf')))
    return False


def run(phase, resume):
    if os.name!='nt':raise RuntimeError('Windows is required')
    if sha(qa.EXE)!=EXE_SHA:
        raise RuntimeError('Exact Frozen EXE SHA mismatch')
    if qa.builder.digest_inventory(qa.builder.source_inventory())!=SOURCE_SHA:
        raise RuntimeError('Current runtime source differs from Frozen source')
    build_report=json.loads((qa.BUILD/'build-report.json').read_text(encoding='utf-8'))
    if (build_report.get('status')!='V106_AAAS_NON_QA_BUILT_NOT_INSTALLED' or
            build_report.get('sourceFreezeSha256')!=SOURCE_SHA or
            build_report.get('exeSha256')!=EXE_SHA or
            build_report.get('installed') is not False):
        raise RuntimeError('Frozen build identity/installation attestation failed')
    baseline=qa.builder.installed_baseline()
    originals=qa.snapshot_pids()
    if any(Path(p.exe()).resolve()==qa.EXE.resolve() for p in
           psutil.process_iter(['name']) if (p.info.get('name') or '').lower()=='taraz.exe'):
        raise RuntimeError('A matching QA EXE is already running')
    if not OUTPUT.exists():acl.secure_private_directory(OUTPUT)
    if resume:
        work=Path(resume).resolve()
        if work.parent!=OUTPUT.resolve() or work.is_symlink() or not (
                work/'synthetic-ownership.json').is_file():
            raise PermissionError('Synthetic QA resume must match a previously created run')
        manifest=json.loads((work/'synthetic-ownership.json').read_text(encoding='utf-8'))
        if manifest!={'syntheticOnly':True,'candidate':BUILD_NAME,'exeSha256':EXE_SHA}:
            raise PermissionError('Synthetic QA manifest mismatch')
    else:
        work=OUTPUT/('qa-'+uuid.uuid4().hex[:12])
        acl.secure_private_directory(work)
        (work/'synthetic-ownership.json').write_text(json.dumps({
            'syntheticOnly':True,'candidate':BUILD_NAME,'exeSha256':EXE_SHA}),encoding='utf-8')
    runtime,roots=synthetic_paths(work)
    if not resume:seed_new_book(roots)
    result={'status':'BLOCKED','phase':phase,'syntheticOnly':True,
            'exeSha256':EXE_SHA,'sourceSha256':SOURCE_SHA,
            'before':book_witness(roots),'installedUnchanged':False,
            'realUserDataRead':False,'forcedProcessTermination':False,
            'usedCDP':False,'qaOwnedProcessExitedGracefully':False}
    handles=[];proc=None
    try:
        probe=work/('native-'+phase+'-'+uuid.uuid4().hex[:8]+'.json')
        env=native.isolated_env(runtime,roots,probe,native.unused_port())
        downloads=None
        if phase=='pdf-invoice':
            downloads=private_download_directory(work)
            result['qaDownloadDirectory']=str(downloads)
            env['TARAZ_QA_PDF_OUTPUT']=str(downloads/'QA-FROZEN-INV-1405-0001.pdf')
        env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']=(
            '--force-renderer-accessibility --disable-background-networking '
            '--disable-sync --disable-component-update --disable-extensions '
            '--no-first-run --proxy-server=http://127.0.0.1:9 '
            '--proxy-bypass-list=<-loopback>')
        for name in ('APPDATA','LOCALAPPDATA','TEMP'):
            if Path(env[name]).resolve()==Path(os.environ[name]).resolve():
                raise PermissionError('Ambient data profile would be exposed')
        qa.PRIVATE_UIA=qa.PRIVATE_UIA.replace(
            "@('بازکردن فهرست بخش‌های تراز','سفارش‌ها','طراحی فرم فاکتور')",
            "@('بازکردن فهرست بخش‌های تراز','سفارش‌ها','طراحی فرم فاکتور','مشتری حضوری','ساده و سریع')",1)
        if phase=='order-cost':
            # Chromium's date-picker Today button has no reliable UIA Invoke.
            # Reuse the pre-audited private-desktop HWND-targeted fallback.
            # This changes only QA's exact-label allowlist, not the app.
            old="'مشتری حضوری','ساده و سریع')"
            if qa.PRIVATE_UIA.count(old)!=1:
                raise RuntimeError('Targeted private calendar QA allowlist changed')
            qa.PRIVATE_UIA=qa.PRIVATE_UIA.replace(old,
                "'مشتری حضوری','ساده و سریع','Today',"
                "'انتخاب تاریخ امروز برای هزینه مرحله 1')",1)
        if phase=='print':
            marker=' # Safely open a new invoice composer AFTER all other screen navigation.'
            if qa.PRIVATE_UIA.count(marker)!=1:
                raise RuntimeError('Private QA print designer insertion point changed')
            qa.PRIVATE_UIA=qa.PRIVATE_UIA.replace(marker,PRINT+marker,1)
        elif phase=='pdf-invoice':
            qa.PRIVATE_UIA=qa.PRIVATE_UIA.replace(
                " $out.status='PRIVATE_OWNED_UIA_RECORDED'",
                PDF_INVOICE+" $out.status='PRIVATE_OWNED_UIA_RECORDED'",1)
        elif phase in ('order-create','order-cost','order-payment'):
            anchor=" $out.status='PRIVATE_OWNED_UIA_RECORDED'"
            if qa.PRIVATE_UIA.count(anchor)!=1:
                raise RuntimeError('Private order injection point changed')
            qa.PRIVATE_UIA=qa.PRIVATE_UIA.replace(anchor,{
                'order-create':ORDERS_CREATE,'order-cost':ORDERS_COST,
                'order-payment':ORDERS_PAYMENT}[phase]+anchor,1)
        else:
            qa.PRIVATE_UIA=qa.PRIVATE_UIA.replace(
                " $out.status='PRIVATE_OWNED_UIA_RECORDED'",
                {'probe':PROBE,'invoice':INVOICE,'proforma':PROFORMA,
                 'invoice-edit':EDIT_INVOICE,'proforma-edit':EDIT_PROFORMA}[phase]+
                " $out.status='PRIVATE_OWNED_UIA_RECORDED'",1)
        with native.PrivateDesktop() as desktop:
            pid,hproc,hthread=desktop.spawn(qa.EXE,work,env)
            handles.extend((hproc,hthread))
            proc=psutil.Process(pid)
            if Path(proc.exe()).resolve()!=qa.EXE.resolve():
                raise RuntimeError('QA process binary is not exact Frozen EXE')
            # On a cold private WebView2 profile the real app can become ready
            # after 28s. Inspect readiness longer; never fabricate a success
            # or launch a second process to compensate for slow startup.
            deadline=time.monotonic()+75
            while time.monotonic()<deadline and not probe.is_file():time.sleep(.3)
            result['startupReportPresent']=probe.is_file()
            if not probe.is_file():
                raise RuntimeError('Synthetic Frozen native startup failed or timed out')
            startup=json.loads(probe.read_text(encoding='utf-8'))
            result['webviewLoaded']=startup.get('loaded') is True
            result['realNativeBridge']=startup.get('accountingBridge')=='function'
            if not(result['webviewLoaded'] and result['realNativeBridge']):
                raise RuntimeError('Frozen WebView/bridge startup not verified')
            owned={pid}
            owned.update(child.pid for child in proc.children(recursive=True))
            result['uia']=owned_uia_long_wait(desktop,owned,work,env)
            result['uiaReportStatus']=result['uia'].get('status')
            if phase!='probe':
                deadline=time.monotonic()+10
                while True:
                    witness=book_witness(roots)
                    result['observedBeforeClose']=witness
                    passed=phase_persisted(phase,witness,downloads)
                    if passed or time.monotonic()>=deadline:
                        result['persistedBeforeClose']=passed
                        break
                    time.sleep(.35)
            if phase=='pdf-invoice':
                documents=list(downloads.glob('*.pdf'))
                result['pdfFileCount']=len(documents)
                result['pdfFile']=(str(documents[0]) if len(documents)==1 else None)
                if len(documents)==1:
                    try:result['pdfIntegrity']=pdf_integrity(documents[0])
                    except Exception as exc:
                        result['pdfIntegrityError']=type(exc).__name__
            windows=qa.owned_window_handles(desktop,owned)
            if len(windows)==1:
                result['ownedWindowClosePosted']=bool(ctypes.windll.user32.PostMessageW(
                    windows[0],0x0010,0,0))
            else:
                result['ownedWindowClosePosted']=False
            try:
                proc.wait(timeout=8)
                result['qaOwnedProcessExitedGracefully']=True
            except psutil.TimeoutExpired:
                result['closeConfirmation']=settle_private_close(desktop,owned,work,env)
                try:
                    proc.wait(timeout=14)
                    result['qaOwnedProcessExitedGracefully']=True
                except psutil.TimeoutExpired:
                    result['remainingQaPid']=pid
    except Exception as exc:
        result['exception']=type(exc).__name__
        result['error']=str(exc)[:180]
    finally:
        for handle in handles:
            if handle:ctypes.windll.kernel32.CloseHandle(handle)
        result['after']=book_witness(roots)
        result['installedUnchanged']=qa.builder.installed_baseline()==baseline
        result['previousTarazPidsPreserved']=all(
            qa.snapshot_pids().get(pid)==created for pid,created in originals.items())
        result['candidateUnchanged']=sha(qa.EXE)==EXE_SHA
        old,new=result['before'],result['after']
        ui=result.get('uia',{})
        ui_ok=result.get('uiaReportStatus')=='PRIVATE_OWNED_UIA_RECORDED'
        safe=(ui_ok and result.get('exception') is None and
              result['qaOwnedProcessExitedGracefully'] and
              result['installedUnchanged'] and
              result['previousTarazPidsPreserved'] and
              result['candidateUnchanged'] and new['journalCount']==0)
        accounting_step=new['revision']==old['revision']+1
        order_step=(new['orderCount']==old['orderCount']==1 and
                    new['orders'][0]['id']==old['orders'][0]['id'] and
                    new['orders'][0]['revision']==old['orders'][0]['revision']+1)
        result['status']='PASS_SYNTHETIC_UIA_PROBE' if (
            phase=='probe' and result.get('webviewLoaded') and
            result.get('uia',{}).get('ownedWindow') is True and
            result['qaOwnedProcessExitedGracefully'] and
            result['installedUnchanged'] and result['previousTarazPidsPreserved']
        ) else 'PASS_FROZEN_SYNTHETIC_INVOICE_DRAFT' if (
            phase=='invoice' and safe and accounting_step and
            old['invoiceCount']==0 and new['invoiceCount']==1 and
            new['invoices'][0]['id']=='INV-1405-0001' and
            new['invoices'][0]['total']==13500 and
            ui.get('syntheticInvoiceUi',{}).get('attemptedSave') and
            ui.get('syntheticInvoiceUi',{}).get('saveInvoked') and
            result['after']['journalCount']==0 and
            result['qaOwnedProcessExitedGracefully'] and result['installedUnchanged']
        ) else 'PASS_FROZEN_SYNTHETIC_PROFORMA_DRAFT' if (
            phase=='proforma' and safe and accounting_step and
            old['proformaCount']==0 and new['proformaCount']==1 and
            new['proformas'][0]['id']=='PF-1405-0001' and
            new['proformas'][0]['total']==5000 and
            ui.get('syntheticProformaUi',{}).get('attemptedSave') and
            ui.get('syntheticProformaUi',{}).get('saveInvoked') and
            result['after']['journalCount']==0 and
            result['qaOwnedProcessExitedGracefully'] and result['installedUnchanged']
        ) else 'PASS_FROZEN_SYNTHETIC_INVOICE_REOPEN_EDIT' if (
            phase=='invoice-edit' and safe and accounting_step and
            old['invoiceCount']==new['invoiceCount']==1 and
            old['invoices'][0]['id']==new['invoices'][0]['id'] and
            old['invoices'][0]['total']==13500 and
            ui.get('syntheticInvoiceEditUi',{}).get('attemptedSave') and
            ui.get('syntheticInvoiceEditUi',{}).get('saveInvoked') and
            result['after']['invoices'][0]['total']==18000 and
            result['after']['invoices'][0]['editedBy']=='local' and
            result['after']['journalCount']==0 and
            result['qaOwnedProcessExitedGracefully'] and result['installedUnchanged']
        ) else 'PASS_FROZEN_SYNTHETIC_PROFORMA_REOPEN_EDIT' if (
            phase=='proforma-edit' and safe and accounting_step and
            old['proformaCount']==new['proformaCount']==1 and
            old['proformas'][0]['id']==new['proformas'][0]['id'] and
            old['proformas'][0]['total']==5000 and
            ui.get('syntheticProformaEditUi',{}).get('attemptedSave') and
            ui.get('syntheticProformaEditUi',{}).get('saveInvoked') and
            result['after']['proformas'][0]['total']==7500 and
            result['after']['proformas'][0]['createdBy']=='local' and
            result['after']['proformas'][0]['editedBy']=='local' and
            result['after']['proformas'][0]['createdAt'] and
            result['after']['proformas'][0]['editedAt'] and
            result['after']['journalCount']==0 and
            result['qaOwnedProcessExitedGracefully'] and result['installedUnchanged']
        ) else 'PASS_FROZEN_SYNTHETIC_PRINT_TEMPLATE' if (
            phase=='print' and safe and
            old['printTemplateCount']==0 and new['printTemplateCount']==1 and
            ui.get('syntheticPrintUi',{}).get('attemptedSave') and
            ui.get('syntheticPrintUi',{}).get('saveInvoked') and
            'QA FROZEN PRIVATE PRINT TEMPLATE' in
            result['after']['printTemplateTitles'] and
            result['after']['journalCount']==0 and
            result['qaOwnedProcessExitedGracefully'] and result['installedUnchanged']
        ) else 'PASS_FROZEN_SYNTHETIC_ORDER_CREATE' if (
            phase=='order-create' and safe and
            old['orderCount']==0 and new['orderCount']==1 and
            ui.get('syntheticOrderCreateUi',{}).get('attemptedSave') and
            ui.get('syntheticOrderCreateUi',{}).get('saveInvoked') and
            result['after']['orders'][0]['revision']==1 and
            result['after']['orders'][0]['quantity']==100 and
            result['after']['orders'][0]['productionQuantity']==120 and
            result['after']['orders'][0]['costStageCount']==1 and
            result['after']['journalCount']==0 and
            result['qaOwnedProcessExitedGracefully'] and result['installedUnchanged']
        ) else 'PASS_FROZEN_SYNTHETIC_ORDER_COST' if (
            phase=='order-cost' and safe and order_step and
            ui.get('syntheticOrderCostUi',{}).get('attemptedRecord') and
            ui.get('syntheticOrderCostUi',{}).get('recordInvoked') and
            len(old['orders'][0]['costRecords'])==0 and
            len(result['after']['orders'][0]['costRecords'])==1 and
            result['after']['orders'][0]['costRecords'][0]['actual_cost']==180000 and
            result['after']['journalCount']==0 and
            result['qaOwnedProcessExitedGracefully'] and result['installedUnchanged']
        ) else 'PASS_FROZEN_SYNTHETIC_ORDER_PAYMENT' if (
            phase=='order-payment' and safe and order_step and
            ui.get('syntheticOrderPaymentUi',{}).get('attemptedSave') and
            ui.get('syntheticOrderPaymentUi',{}).get('saveInvoked') and
            len(old['orders'][0]['payments'])==0 and
            len(result['after']['orders'][0]['payments'])==1 and
            result['after']['orders'][0]['payments'][0]['amount']==500000 and
            result['after']['orders'][0]['payments'][0]['status']=='recorded' and
            result['after']['journalCount']==0 and
            result['qaOwnedProcessExitedGracefully'] and result['installedUnchanged']
        ) else 'PASS_FROZEN_SYNTHETIC_INVOICE_PDF' if (
            phase=='pdf-invoice' and safe and
            ui.get('syntheticPdfUi',{}).get('attemptedDownload') and
            ui.get('syntheticPdfUi',{}).get('downloadInvoked') and
            result.get('pdfIntegrity',{}).get('headerValid') and
            result['pdfIntegrity']['hasEof'] and
            result['pdfIntegrity']['pageCount']>=1 and
            result['pdfIntegrity']['pageCount']==result['pdfIntegrity']['jpegPageCount'] and
            result['pdfIntegrity']['renderedContentNonblank'] and
            result['after']['journalCount']==0 and
            result['qaOwnedProcessExitedGracefully'] and result['installedUnchanged']
        ) else 'BLOCKED'
        report=work/('synthetic-'+phase+'-'+uuid.uuid4().hex[:8]+'.json')
        report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result,report,work


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--phase',choices=('probe','invoice','proforma',
                                          'invoice-edit','proforma-edit','print',
                                          'order-create','order-cost',
                                          'order-payment','pdf-invoice'),required=True)
    parser.add_argument('--resume')
    args=parser.parse_args()
    data,report,work=run(args.phase,args.resume)
    print(json.dumps({'status':data['status'],'report':str(report),'work':str(work),
        'startup':data.get('startupReportPresent'),
        'before':data['before'],'after':data['after'],
        'uia':next((data.get('uia',{}).get(key) for key in
            ('syntheticInventory','syntheticInvoiceUi','syntheticProformaUi',
             'syntheticInvoiceEditUi','syntheticProformaEditUi',
             'syntheticPrintUi','syntheticOrderCreateUi','syntheticOrderCostUi',
             'syntheticOrderPaymentUi','syntheticPdfUi')
             if key in data.get('uia',{})),None),
        'error':data.get('error'),'graceful':data['qaOwnedProcessExitedGracefully'],
        'installedUnchanged':data['installedUnchanged']},ensure_ascii=True))
    raise SystemExit(0 if data['status'].startswith('PASS') else 1)
