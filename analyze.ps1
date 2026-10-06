# EduMatch 一条命令跑完分析（Windows / PowerShell）
#
#   .\analyze.ps1 "分析北京工业大学信息管理与信息系统专业与数据分析师岗位的匹配度"
#   .\analyze.ps1 "…" -Occupation "数据分析师" -MicroFile "个人画像.txt" -Scope all
#   .\analyze.ps1 "…" -OfferUrl "北京工业大学=https://www.bjut.edu.cn/"   # 大模型检索到的官网
#   .\analyze.ps1 "…" -Offline                                           # 不联网
#
# 会自动：插件补采（点名院校时）→ 引擎分析 → 分层报告(MD+HTML) → 质量门。
param(
  [Parameter(Mandatory = $true, Position = 0)][string]$Query,
  [string]$Occupation = "",
  [string]$Scope = "all",
  [string]$MicroFile = "",
  [string]$OutDir = "",
  [int]$PeerMax = 2,
  [string[]]$OfferUrl = @(),
  [string]$HarvestMode = "target",   # target=本校+同类院校；region=区域高校按批推进
  [int]$HarvestBatch = 3,            # region 模式每轮采几所
  [switch]$NoHarvest,
  [switch]$Offline,
  [switch]$Ask,      # 只打印问询清单（首轮与用户确认用）
  [switch]$Force     # 目标不明确也直接跑（不推荐）
)

$ErrorActionPreference = "Stop"
$Core = $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
$python = if ($env:EDUMATCH_PYTHON) { $env:EDUMATCH_PYTHON } else { "python" }

$args = @("$Core\scripts\analyze.py", "--query", $Query, "--scope", $Scope, "--peer-max", $PeerMax)
if ($Occupation) { $args += @("--occupation", $Occupation) }
if ($MicroFile)  { $args += @("--micro-file", $MicroFile) }
if ($OutDir)     { $args += @("--out-dir", $OutDir) }
if ($NoHarvest)  { $args += "--no-auto-harvest" }
if ($Offline)    { $args += "--offline" }
if ($HarvestMode -ne "target") { $args += @("--harvest-mode", $HarvestMode, "--harvest-batch", $HarvestBatch) }
if ($Ask)        { $args += "--ask" }
if ($Force)      { $args += "--force" }
foreach ($u in $OfferUrl) { $args += @("--domain-candidate", $u) }

Push-Location $Core
try { & $python @args } finally { Pop-Location }
