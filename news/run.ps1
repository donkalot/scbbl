# Daily SC BBL news check: Claude researches and commits curated data; this script guards git and pushes.
# Run by the "SC BBL news check" scheduled task. The parameters are for tests/test_news_run.py.
param(
  [string]$Repo = 'C:\play\scbbl',
  [string]$State = 'C:\Users\pcolla\scbbl-news',
  [string]$Claude,
  [string]$UserSettings = "$env:USERPROFILE\.claude\settings.json",
  [switch]$NoVerify,
  [switch]$Quiet
)
$ErrorActionPreference = 'Stop'
$Logs = Join-Path $State 'logs'
# Present only while a run is going; finding it at start means the last run was killed (sleep, time limit).
$Marker = Join-Path $State 'running'
# The only paths a news run may change. Leftovers or commits touching anything else stop the run.
# JSON only: anything under data/ is served from the live site, so an .html there would be a page.
# curated/sc_raw is SuperCoach's own JSON, saved by hand; only the user changes it.
$Allowed = '^((curated/(?!(?i:sc_raw)/)|data/)[\w/.-]+\.json|news/open-items\.md)$'
# Claude reads fetched web pages, so it gets exact commands and path-scoped edits, never a free shell.
# Read, Glob and Grep stay unlisted: unlisted, they reach only the repo; allowing them opens the whole disk.
$Tools = 'WebSearch', 'WebFetch',
  'Edit(curated/**)', 'Write(curated/**)', 'Edit(news/open-items.md)',
  'Bash(python -m pipeline.build)', 'Bash(python -m pytest -q)', 'Bash(node --test tests/ worker/test/)',
  'Bash(git status)', 'Bash(git diff)', 'Bash(git checkout -- curated data)',
  'Bash(git add curated data news/open-items.md)', 'Bash(git commit -m *)'
$Deny = 'Read(./worker/.dev.vars)', 'Read(./worker/.wrangler/**)', 'Edit(curated/sc_raw/**)', 'Write(curated/sc_raw/**)'
New-Item -ItemType Directory -Force $Logs | Out-Null
$Log = Join-Path $Logs ((Get-Date -Format 'yyyy-MM-dd_HHmm') + '.log')
$OutputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false

function Say($m) { "$(Get-Date -Format 'HH:mm:ss') $m" | Out-File $Log -Append -Encoding utf8 }

function Toast($title, $body) {
  Say "$title - $body"
  if ($Quiet) { return }
  try {
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    $x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
    $t = $x.GetElementsByTagName('text')
    $t.Item(0).AppendChild($x.CreateTextNode($title)) | Out-Null
    $t.Item(1).AppendChild($x.CreateTextNode("$body`n$Log")) | Out-Null
    $app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))
  } catch { Say "toast failed: $_" }
}

function Invoke-Git { & git.exe @args; if ($LASTEXITCODE) { throw "git $args failed ($LASTEXITCODE)" } }
function Invoke-Remote { Invoke-Git -c credential.helper= -c 'credential.helper=!gh auth git-credential' @args }

function Sync {
  try { Invoke-Remote pull --rebase --quiet }
  catch {
    # Left mid-rebase, every later run would stop at the branch check with a misleading message.
    if ((Test-Path .git/rebase-merge) -or (Test-Path .git/rebase-apply)) { Invoke-Git rebase --abort }
    throw "pull --rebase failed, so the local commits need rebasing by hand ($_)"
  }
}

function Stop-Run($title, $body) { Toast $title $body; exit 1 }

# --no-renames: a rename lists only its new name, which would hide the deletion of the old path.
function Changed { @(git diff --no-renames --name-only @args) }

function Outside($files) { @($files | Where-Object { $_ -and $_ -cnotmatch $Allowed }) }

# Ignored files count too under the news paths, so a planted curated/.gitignore can't hide anything.
function Untracked { @(git ls-files --others --exclude-standard) + @(git ls-files --others -- curated data news) | Sort-Object -Unique }

function GitState { (Get-ChildItem .git/config, .git/hooks -File -Recurse | Get-FileHash).Hash -join ',' }

Set-Location $Repo
$started = $false
try {
  if ((git rev-parse --abbrev-ref HEAD) -ne 'main') { Stop-Run 'SC BBL news check skipped' "$Repo is not on main." }

  if (Test-Path $Marker) {
    Say "the run started $(Get-Content $Marker) was interrupted"
    $left = @(Changed HEAD) + @(git ls-files --others --exclude-standard -- curated data news)
    if ($left) {
      $bad = Outside $left
      if ($bad) { Stop-Run 'SC BBL news check skipped' "An interrupted run left changes, including outside the news paths: $($bad -join ', ')" }
      # Stash rather than discard: the half-finished edits stay recoverable with git stash list / pop.
      Invoke-Git stash push --quiet --include-untracked -m "news check: leftovers from the run started $(Get-Content $Marker)" -- @left
      Say "stashed its leftovers: $($left -join ', ')"
    }
  }
  if (git status --porcelain --untracked-files=no) { Stop-Run 'SC BBL news check skipped' "$Repo has uncommitted changes." }

  Set-Content $Marker (Get-Date -Format 's')
  $started = $true
  # Hold off idle sleep until this process exits. Modern Standby suspends the run otherwise, and the
  # task's time limit later kills it with half-written edits (21 Nov). 2147483649 = ES_CONTINUOUS | ES_SYSTEM_REQUIRED.
  Add-Type -Namespace Win32 -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
  if (-not [Win32.Power]::SetThreadExecutionState([uint32]2147483649)) { Say 'could not hold off sleep' }

  Sync
  # Compare against the remote, not HEAD, so a news commit an earlier run made but never pushed goes out too.
  $before = git rev-parse '@{u}'
  $bad = Outside (Changed $before HEAD)
  if ($bad) { Stop-Run 'SC BBL news check skipped' "Unpushed local commits touch files outside the news paths: $($bad -join ', ')" }
  Say "start at $(git rev-parse HEAD), remote at $before"

  if (-not $Claude) {
    $Claude = (Get-ChildItem "$env:USERPROFILE\.vscode\extensions\anthropic.claude-code-*-win32-x64\resources\native-binary\claude.exe" |
      Sort-Object { [version]($_.FullName -replace '.*claude-code-([\d.]+)-.*', '$1') } | Select-Object -Last 1).FullName
    if (-not $Claude) { Stop-Run 'SC BBL news check failed' 'claude.exe not found in the VS Code extension.' }
  }
  # User settings allow a bare Bash, so they aren't loaded. Take only the API env and model from them.
  $settings = Get-Content $UserSettings -Raw -Encoding utf8 | ConvertFrom-Json
  if ($settings.env) { foreach ($p in $settings.env.PSObject.Properties) { Set-Item "env:$($p.Name)" $p.Value } }
  $model = if ($settings.model) { '--model', $settings.model } else { @() }
  $prompt = "Today is $(Get-Date -Format 'yyyy-MM-dd').`n`n" + (Get-Content (Join-Path $Repo 'news\prompt.md') -Raw -Encoding utf8)
  $untracked = @(Untracked)
  $gitState = GitState
  $out = $prompt | & $Claude -p --output-format text --setting-sources project @model --allowedTools @Tools --disallowedTools @Deny
  $code = $LASTEXITCODE
  $out | Out-File $Log -Append -Encoding utf8
  $result = ($out | Select-String '^RESULT:' | Select-Object -Last 1).Line
  if (-not $result) { $result = "no RESULT line (claude exit $code)" }

  if ((GitState) -ne $gitState) { Stop-Run 'SC BBL news check needs a look' "Git config or hooks changed during the run. $result" }
  if ((git rev-parse --abbrev-ref HEAD) -ne 'main') { Stop-Run 'SC BBL news check needs a look' "The run left $Repo off main. $result" }
  $new = @(Untracked | Where-Object { $_ -notin $untracked })
  if ($new) { Stop-Run 'SC BBL news check needs a look' "The run left new files: $($new -join ', '). $result" }
  $left = @(Changed HEAD)
  if ($left | Where-Object { $_ -ne 'news/open-items.md' }) { Stop-Run 'SC BBL news check needs a look' "Uncommitted changes left in $Repo. $result" }
  if ($left) { Invoke-Git commit --quiet -m "News check notes $(Get-Date -Format 'yyyy-MM-dd')" -- news/open-items.md }
  $ok = $code -eq 0 -and $result -match '^RESULT: (nothing new|committed)'

  if ((git rev-parse HEAD) -eq $before) {
    if ($ok -and $result -match '^RESULT: nothing new') { Say "no commit: $result" } else { Toast 'SC BBL news check needs a look' $result }
    exit 0
  }
  $bad = Outside (Changed $before HEAD)
  if ($bad) { Stop-Run 'SC BBL news check: not pushed' "Commit touches files outside the news paths: $($bad -join ', ')" }

  # Rebase onto anything pushed during the run first, so the tests below check what actually goes out.
  Sync
  $data = @(Changed '@{u}' HEAD | Where-Object { $_ -match '^(curated|data)/' })
  if ($data -and -not $NoVerify) {
    Say 'verifying before push'
    cmd /c "python -m pytest -q >> `"$Log`" 2>&1"; if ($LASTEXITCODE) { Stop-Run 'SC BBL news check: not pushed' 'pytest failed after the commit.' }
    cmd /c "node --test tests/ worker/test/ >> `"$Log`" 2>&1"; if ($LASTEXITCODE) { Stop-Run 'SC BBL news check: not pushed' 'node tests failed after the commit.' }
  }
  $msg = (git log --format=%s '@{u}..HEAD') -join '; '
  Invoke-Remote push --quiet origin HEAD:refs/heads/main
  Say "pushed: $msg"
  if (-not $ok) { Toast 'SC BBL news check needs a look' "Pushed $msg, but: $result" }
  elseif ($data) { Toast 'SC BBL updated' $msg }
} catch {
  Stop-Run 'SC BBL news check failed' "$_"
}
finally {
  if ($started) { Remove-Item $Marker -ErrorAction SilentlyContinue }
  Get-ChildItem $Logs -Filter *.log | Sort-Object Name | Select-Object -SkipLast 60 | Remove-Item -Force
}
