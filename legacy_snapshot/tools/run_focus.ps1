# run_focus.ps1 — run the STABILISED Dolphin path (2s windows + verified direct merge).
# Usage:
#   .\run_focus.ps1 -Video demo1\mix.mp4 -Out out_focus -Speakers 2
#   .\run_focus.ps1 -Video clip.mp4 -Out out_focus -Boxes "x1,y1,x2,y2"   # pick one face
# Requires A:\focus\.venv (see A:\focus\requirements.freeze.txt). Writes:
#   <Out>\speaker{1..N}_est.wav, audio.wav, mouthroi\*.npz, landmark\*.npz
param(
    [Parameter(Mandatory=$true)][string]$Video,
    [string]$Out = "out_focus",
    [int]$Speakers = 2,
    [string]$Boxes = ""
)
$A  = "A:\focus"
& "$A\env.ps1"
$py     = "$A\.venv\Scripts\python.exe"
$script = "$A\Dolphin\Inference_focus.py"

Push-Location "$A\Dolphin"
$argv = @($script, "-i", $Video, "-o", $Out, "--speakers", $Speakers)
if ($Boxes) { $argv += @("--face-boxes", $Boxes) }
& $py @argv
$code = $LASTEXITCODE
Pop-Location
Write-Host "run_focus exit=$code  outputs in $A\Dolphin\$Out"
