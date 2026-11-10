param(
    [string]$HostName = "wsl-build",
    [string]$Ref = "HEAD",
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version,
    [string]$OutputDirectory = "dist"
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$archive = Join-Path ([IO.Path]::GetTempPath()) (
    "SerrebiTorrent-source-{0}.zip" -f [guid]::NewGuid().ToString("N")
)
$remoteRoot = $null

function Invoke-Native {
    param([scriptblock]$Command, [string]$Description)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

Push-Location $root
try {
    Invoke-Native { git rev-parse --verify "$Ref^{commit}" | Out-Null } "Git ref validation"
    Invoke-Native { git archive --format=zip --output="$archive" $Ref } "Source archive creation"

    $remoteRoot = (& ssh -o BatchMode=yes $HostName "mktemp -d /root/SerrebiTorrent-app-build.XXXXXX").Trim()
    if ($LASTEXITCODE -ne 0 -or $remoteRoot -notmatch '^/root/SerrebiTorrent-app-build\.[A-Za-z0-9]+$') {
        throw "The remote host did not return a safe build directory: $remoteRoot"
    }

    Invoke-Native { scp -q "$archive" "${HostName}:${remoteRoot}/source.zip" } "Source upload"

    # Keep this a single line with no embedded double quotes or newlines. A
    # multi-line string loses its quoting on the way through ssh, which turns
    # "set -Eeuo pipefail" into a bare "set" that dumps the remote environment
    # and silently drops the error handling. A login shell is not used, so the
    # remote profile cannot print secrets into the build log.
    # The build runs in a debian:trixie container (glibc 2.41), not on the
    # builder itself: the default builder is local WSL Ubuntu 26.04 (glibc
    # 2.43), whose binaries would not start on older distros. Host caches keep
    # apt .debs, uv (incl. the source-built wxPython wheel) and the libtorrent
    # wheels between builds. $remoteRoot is validated above, so it needs no
    # quoting inside the single-quoted container script.
    $container = (
        "rm -f /etc/apt/apt.conf.d/docker-clean; " +
        "apt-get update -qq; " +
        "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends " +
        "curl ca-certificates pkg-config build-essential binutils libgtk-3-dev libtiff-dev libwebp-dev " +
        "libayatana-appindicator3-1 gir1.2-ayatanaappindicator3-0.1 " +
        # Runtime libraries the wxPython/libtorrent .so files link against (ldd).
        "libegl1 libgl1 libsdl2-2.0-0 libsm6 libxtst6 libxxf86vm1 libcurl4t64 libgstreamer1.0-0 " +
        "libgstreamer-plugins-bad1.0-0 libjavascriptcoregtk-4.1-0 libnotify4 libpcre2-32-0 " +
        "libwebkit2gtk-4.1-0 libwebpdemux2 >/dev/null; " +
        "curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null; " +
        "bash $remoteRoot/source/tools/build_linux.sh"
    )
    $remoteCommand = (
        "set -Eeuo pipefail; " +
        "mkdir -p '$remoteRoot/source'; " +
        "unzip -q '$remoteRoot/source.zip' -d '$remoteRoot/source'; " +
        "docker run --rm --cpu-shares 26214 " +
        "-v '${remoteRoot}:${remoteRoot}' " +
        "-v /root/libtorrent-build/wheels:/root/libtorrent-build/wheels:ro " +
        "-v /var/cache/release-build/serrebitorrent-apt:/var/cache/apt/archives " +
        "-v /var/cache/release-build/uv:/root/.cache/uv " +
        "-e SERREBITORRENT_BUILD_VERSION='$Version' " +
        "debian:trixie bash -c '$container'"
    )
    Invoke-Native { ssh -o BatchMode=yes $HostName $remoteCommand } "Remote Linux build"

    $output = [IO.Path]::GetFullPath((Join-Path $root $OutputDirectory))
    New-Item -ItemType Directory -Force -Path $output | Out-Null
    $artifact = "SerrebiTorrent-v$Version-linux-x86_64.tar.gz"
    Invoke-Native {
        scp -q "${HostName}:${remoteRoot}/source/dist/$artifact" (Join-Path $output $artifact)
    } "Linux artifact download"
    Write-Host "Linux package: $(Join-Path $output $artifact)"
}
finally {
    Pop-Location
    if (Test-Path -LiteralPath $archive) {
        Remove-Item -LiteralPath $archive -Force
    }
    if ($remoteRoot -and $remoteRoot -match '^/root/SerrebiTorrent-app-build\.[A-Za-z0-9]+$') {
        & ssh -o BatchMode=yes $HostName "rm -rf -- '$remoteRoot'" | Out-Null
    }
}
