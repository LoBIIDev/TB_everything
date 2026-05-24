# SWGoH TB local refresh — fetch guild rosters, regenerate HTML + Line message, push to GitHub.
# Run by Windows Task Scheduler every 3 hours.
# Manual invocation: powershell -ExecutionPolicy Bypass -File C:\Users\USER\Documents\Projects\swgoh_TB\refresh-tb.ps1

$RepoRoot = "C:\Users\USER\Documents\Projects\swgoh_TB"
$Python = "C:\Users\USER\anaconda3\python.exe"
$LogDir = Join-Path $RepoRoot "logs"
$LogFile = Join-Path $LogDir ("refresh-{0}.log" -f (Get-Date -Format "yyyyMMdd"))

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

function Log {
    param([string]$Msg)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Msg
    Add-Content -Path $LogFile -Value $line -Encoding utf8
    Write-Output $line
}

# Run a command line via cmd.exe so stderr/stdout merge cleanly without PowerShell 5.1
# wrapping stderr lines in NativeCommandError records.
function RunCmd {
    param([string]$Name, [string]$CmdLine, [switch]$LogTailOnly)
    Log "==> $Name"
    $out = cmd.exe /c "$CmdLine 2>&1"
    $exit = $LASTEXITCODE
    if ($out) {
        $text = ($out -join "`n").TrimEnd()
        if ($LogTailOnly) {
            $text = ($text -split "`n" | Select-Object -Last 5) -join "`n"
        }
        if ($text) { Log $text }
    }
    if ($exit -ne 0) {
        Log "    FAIL: $Name (exit $exit)"
        throw "$Name failed (exit $exit)"
    }
    Log "    OK: $Name"
}

Set-Location $RepoRoot
$env:PYTHONIOENCODING = "utf-8"

Log "===== refresh start ====="

try {
    RunCmd "git pull --rebase --autostash" "git pull --rebase --autostash"
    RunCmd "fetch_guild.py --force" "`"$Python`" fetch_guild.py --force" -LogTailOnly
    RunCmd "generate_html.py" "`"$Python`" generate_html.py" -LogTailOnly
    RunCmd "line_message.py" "`"$Python`" line_message.py"

    Log "==> git add docs/index.html docs/line_message.txt claims.yaml"
    cmd.exe /c "git add docs/index.html docs/line_message.txt claims.yaml 2>&1" | Out-Null

    $staged = cmd.exe /c "git diff --staged --name-only 2>&1"
    if ([string]::IsNullOrWhiteSpace(($staged -join ""))) {
        Log "    no output changes — skip commit/push"
    } else {
        Log "    staged: $(($staged | Where-Object { $_ }) -join ', ')"
        $stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm 'UTC'")
        $msg = "auto: local TB refresh ($stamp)"
        RunCmd "git commit" "git commit -m `"$msg`""
        RunCmd "git push" "git push"
    }

    Log "===== refresh OK ====="
    exit 0
} catch {
    Log "===== refresh FAILED: $($_.Exception.Message) ====="
    exit 1
}
