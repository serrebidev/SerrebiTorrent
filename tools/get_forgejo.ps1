$ErrorActionPreference = "Stop"

$url = git remote get-url forgejo 2>$null
if ($url -match "^(?:https?://|ssh://|[^@]+@)(?<host>[^:/]+)[:/](?<repo>.+?)(\.git)?$") {
    Write-Output ("FORGEJO_HOST={0}" -f $Matches.host)
    Write-Output ("FORGEJO_REPO={0}" -f $Matches.repo)
}
