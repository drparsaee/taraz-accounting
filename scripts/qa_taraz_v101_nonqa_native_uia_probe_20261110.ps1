param(
  [Parameter(Mandatory=$true)][int]$QaPid,
  [Parameter(Mandatory=$true)][string]$ResultFile
)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

function Observe([System.Windows.Automation.AutomationElement]$win) {
  $wanted = @('بازکردن فهرست بخش‌های تراز','طراحی فرم فاکتور',
    'نام قالب','ذخیره قالب چاپ','طراح قالب چاپ فاکتور','قالب چاپ ذخیره‌شده')
  $seen = @{}
  foreach($key in $wanted) {$seen[$key] = $false}
  $all=$win.FindAll([System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)
  foreach($element in $all) {
    $name=$element.Current.Name
    if($wanted -contains $name) { $seen[$name] = $true }
  }
  return @{ descendants=$all.Count;
    menuTrigger=[bool]$seen['بازکردن فهرست بخش‌های تراز'];
    invoiceDesignerNav=[bool]$seen['طراحی فرم فاکتور'];
    designerTitleInput=[bool]$seen['نام قالب'];
    saveButton=[bool]$seen['ذخیره قالب چاپ'];
    printDesigner=[bool]$seen['طراح قالب چاپ فاکتور'];
    savedTemplateSelect=[bool]$seen['قالب چاپ ذخیره‌شده'] }
}

$root=[System.Windows.Automation.AutomationElement]::RootElement
$roots=$root.FindAll([System.Windows.Automation.TreeScope]::Children,
  [System.Windows.Automation.Condition]::TrueCondition)
$descendants=@($QaPid)
$procs=@(Get-CimInstance Win32_Process -ErrorAction Stop)
for($iteration=0;$iteration -lt 6;$iteration++){
  $added=@()
  foreach($p in $procs){
    if(($descendants -contains [int]$p.ParentProcessId) -and
       ($descendants -notcontains [int]$p.ProcessId)){$added+=([int]$p.ProcessId)}
  }
  if($added.Count -eq 0){break}
  $descendants+=@($added)
}
$windows=@()
foreach($item in $roots){
  if($item.Current.Name -like '*تراز*'){
    $windows+=@{element=$item;ownerPid=$item.Current.ProcessId}
  }
}
$candidate=$null
foreach($item in $windows) {
  if($descendants -contains $item.ownerPid) {$candidate=$item.element; break}
}
$result=@{status='WINDOW_NOT_FOUND';qaPid=$QaPid;windowMatches=$windows.Count;
          qaProcessDescendantCount=$descendants.Count}
if($null -ne $candidate){
  $info=Observe $candidate
  $result=@{status='WINDOW_FOUND';qaPid=$QaPid;nativeWindowOwnerPid=$candidate.Current.ProcessId;
            titleIsTaraz=($candidate.Current.Name -like '*تراز*');
            descendants=$info.descendants;menuTrigger=$info.menuTrigger;
            invoiceDesignerNav=$info.invoiceDesignerNav;
            designerTitleInput=$info.designerTitleInput;
            saveButton=$info.saveButton;printDesigner=$info.printDesigner;
            savedTemplateSelect=$info.savedTemplateSelect;
            qaProcessDescendantCount=$descendants.Count}
}
$payload=$result|ConvertTo-Json -Depth 5 -Compress
[IO.File]::WriteAllText($ResultFile,$payload,[Text.UTF8Encoding]::new($false))
if($result.status -ne 'WINDOW_FOUND'){exit 3}
