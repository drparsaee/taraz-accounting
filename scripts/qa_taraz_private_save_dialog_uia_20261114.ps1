param([Parameter(Mandatory=$true)][long]$TargetWindow,
      [Parameter(Mandatory=$true)][string]$ResultFile)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root=[System.Windows.Automation.AutomationElement]::FromHandle(
  [IntPtr]::new($TargetWindow))
if($null -eq $root -or $root.Current.Name -ne 'Save As' -or
   $root.Current.ClassName -ne '#32770'){
  throw 'Not the scoped native Windows Save As dialog'
}
$out=@{status='READ_ONLY_SAVE_DIALOG_UIA';pid=[int]$root.Current.ProcessId;
       name=[string]$root.Current.Name;controls=@()}
$controls=$root.FindAll(
  [System.Windows.Automation.TreeScope]::Descendants,
  [System.Windows.Automation.Condition]::TrueCondition)
foreach($item in $controls){
  if($out.controls.Count -ge 160){break}
  $pattern=$null
  $valueSupported=$item.TryGetCurrentPattern(
    [System.Windows.Automation.ValuePattern]::Pattern,[ref]$pattern)
  $out.controls+=@{
    name=[string]$item.Current.Name
    automationId=[string]$item.Current.AutomationId
    type=[string]$item.Current.ControlType.ProgrammaticName
    className=[string]$item.Current.ClassName
    enabled=[bool]$item.Current.IsEnabled
    valuePattern=[bool]$valueSupported
    value=if($valueSupported){[string]$pattern.Current.Value}else{''}
  }
}
[System.IO.File]::WriteAllText($ResultFile,
  ($out|ConvertTo-Json -Depth 7),[System.Text.UTF8Encoding]::new($false))
