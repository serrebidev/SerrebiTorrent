@echo off
setlocal enableextensions enabledelayedexpansion

set "APP_NAME=SerrebiTorrent"
set "EXE_NAME=SerrebiTorrent.exe"
set "VERSION_FILE=app_version.py"
set "MANIFEST_NAME=SerrebiTorrent-update.json"
set "DEFAULT_SIGNTOOL=C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe"
set "FORGEJO_HOST=git.serrebiradio.com"
set "FORGEJO_REPO=serrebi/SerrebiTorrent"
set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Launcher\py.exe -3.14"
if not exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" set "PYTHON_CMD=py.exe -3.14"

if "%SIGNTOOL_PATH%"=="" (
    set "SIGNTOOL_PATH=%DEFAULT_SIGNTOOL%"
)

set "MODE=%~1"
if "%MODE%"=="" set "MODE=build"

if /I "%MODE%"=="help" goto :usage
if /I not "%MODE%"=="release" if /I not "%MODE%"=="build" if /I not "%MODE%"=="dry-run" goto :usage

set "DRY_RUN=0"
if /I "%MODE%"=="dry-run" set "DRY_RUN=1"

echo ========================================
echo SerrebiTorrent build: %MODE%
echo ========================================

set "ROOT=%~dp0"
pushd "%ROOT%"

if not defined LIBTORRENT_WHEEL_DIR set "LIBTORRENT_WHEEL_DIR=%USERPROFILE%\libtorrent-build\wheels"
set "BUILD_VENV=%ROOT%build\venv"
set "BUILD_PYTHON=%BUILD_VENV%\Scripts\python.exe"

%PYTHON_CMD% --version >nul 2>&1 || (echo Python 3.14 not found.& goto :error)

if /I "%MODE%"=="release" if defined SIGN_CERT_THUMBPRINT (
    set "SIGN_CERT_THUMBPRINT=%SIGN_CERT_THUMBPRINT: =%"
)

if /I "%MODE%"=="release" (
    where git >nul 2>&1 || (echo Git not found in PATH.& goto :error)
    if not defined FORGEJO_TOKEN (echo FORGEJO_TOKEN is not set. Copy it from /root/forgejo-muse-token.txt on root@serrebiradio.com.& goto :error)
    call :detect_forgejo
    call :ensure_tracked_tree_clean || goto :error
    call :ensure_packageable_untracked_clean || goto :error
)

if /I "%MODE%"=="release" (
    echo Fetching tags...
    git fetch --tags forgejo
    if errorlevel 1 (
        echo Failed to fetch tags.
        goto :error
    )
)
if /I "%MODE%"=="dry-run" (
    echo Fetching tags...
    git fetch --tags forgejo
    if errorlevel 1 (
        echo Failed to fetch tags.
        goto :error
    )
)

if /I "%MODE%"=="release" (
    call :compute_version_and_notes || goto :error
    echo Next version: !NEXT_VERSION!
    if %DRY_RUN%==1 (
        echo DRY RUN: would update %VERSION_FILE% to !NEXT_VERSION!.
    ) else (
        call :update_version_file || goto :error
        call :update_changelog || goto :error
    )
) else if /I "%MODE%"=="dry-run" (
    set "RELEASE_NOTES=%TEMP%\SerrebiTorrent_release_notes.txt"
    call :compute_version_and_notes || goto :error
    echo Next version: !NEXT_VERSION!
) else (
    call :read_current_version || goto :error
    set "NEXT_VERSION=!CURRENT_VERSION!"
)

if %DRY_RUN%==1 (
    echo DRY RUN: would build, sign, and zip version !NEXT_VERSION!.
    if /I "%MODE%"=="release" (
        echo DRY RUN: would create manifest, commit, tag, push, and create Forgejo release.
    )
    popd
    exit /b 0
)

echo Cleaning previous build artifacts...
taskkill /F /IM %EXE_NAME% /T >nul 2>&1
if exist build rd /s /q build
if exist dist rd /s /q dist
if exist build (
    powershell -NoProfile -Command "Remove-Item -Recurse -Force 'build'" >nul 2>&1
)
if exist dist (
    powershell -NoProfile -Command "Remove-Item -Recurse -Force 'dist'" >nul 2>&1
)
if exist build (
    echo Failed to delete build directory.
    goto :error
)
if exist dist (
    echo Failed to delete dist directory.
    goto :error
)

echo Selecting the maintained CPython 3.14 libtorrent wheel...
set "LIBTORRENT_WHEEL="
set "LIBTORRENT_VERSION="
for /f "delims=" %%A in ('%PYTHON_CMD% tools\select_libtorrent_wheel.py --wheel-dir %LIBTORRENT_WHEEL_DIR% --platform-pattern win_amd64 --format cmd') do set "%%A"
if not defined LIBTORRENT_WHEEL (
    echo No suitable libtorrent wheel was selected.
    goto :error
)

echo Creating isolated build environment...
%PYTHON_CMD% -m venv "%BUILD_VENV%"
if errorlevel 1 goto :error
"%BUILD_PYTHON%" -m pip install --disable-pip-version-check --requirement requirements.txt --requirement requirements-build.txt
if errorlevel 1 goto :error
"%BUILD_PYTHON%" -m pip install --disable-pip-version-check --force-reinstall --no-deps "%LIBTORRENT_WHEEL%"
if errorlevel 1 goto :error
for /f "delims=" %%V in ('call "%BUILD_PYTHON%" -c "import libtorrent; print(libtorrent.__version__)"') do set "LIBTORRENT_VERSION=%%V"
if not defined LIBTORRENT_VERSION (
    echo Failed to import libtorrent in the isolated build environment.
    goto :error
)
echo Using libtorrent !LIBTORRENT_VERSION! from %LIBTORRENT_WHEEL%.

echo Running PyInstaller...
"%BUILD_PYTHON%" -m PyInstaller SerrebiTorrent.spec --noconfirm
if errorlevel 1 goto :error

echo Verifying self-contained packaged runtime...
"%BUILD_PYTHON%" tools\audit_bundle.py "dist\%APP_NAME%"
if errorlevel 1 goto :error
"%BUILD_PYTHON%" tools\verify_frozen.py "dist\%APP_NAME%\%EXE_NAME%" "build\frozen-self-test.json" --expected-libtorrent "!LIBTORRENT_VERSION!"
if errorlevel 1 goto :error

if not exist "%SIGNTOOL_PATH%" (
    echo SignTool not found: "%SIGNTOOL_PATH%"
    goto :error
)

pushd "dist\%APP_NAME%"
echo Signing %EXE_NAME%...
set "SIGNTOOL_CERT_ARGS=/a"
if defined SIGN_CERT_THUMBPRINT (
    set "SIGNTOOL_CERT_ARGS=/sha1 %SIGN_CERT_THUMBPRINT%"
)
"%SIGNTOOL_PATH%" sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 %SIGNTOOL_CERT_ARGS% ".\%EXE_NAME%"
if errorlevel 1 (popd & goto :error)
popd

set "ZIP_NAME=%APP_NAME%-v%NEXT_VERSION%.zip"
set "ZIP_PATH=%CD%\dist\%ZIP_NAME%"
echo Creating release ZIP: %ZIP_NAME%
powershell -NoProfile -Command "Compress-Archive -Path 'dist\%APP_NAME%' -DestinationPath '%ZIP_PATH%' -Force"
if errorlevel 1 goto :error

echo Creating latest ZIP: %APP_NAME%.zip
powershell -NoProfile -Command "Compress-Archive -Path 'dist\%APP_NAME%' -DestinationPath 'dist\%APP_NAME%.zip' -Force"
if errorlevel 1 goto :error

if /I "%MODE%"=="release" (
    if defined SERREBITORRENT_LINUX_TARBALL (
        rem A prebuilt Linux package was supplied; skip the SSH build.
        echo Using prebuilt Linux package "!SERREBITORRENT_LINUX_TARBALL!"...
        copy /Y "!SERREBITORRENT_LINUX_TARBALL!" "dist\%APP_NAME%-v!NEXT_VERSION!-linux-x86_64.tar.gz" >nul
        if errorlevel 1 goto :error
    ) else (
        echo Building Linux release on root@serrebiradio.com...
        powershell -NoProfile -File "tools\build_linux_remote.ps1" -Ref HEAD -Version "!NEXT_VERSION!" -OutputDirectory "dist"
        if errorlevel 1 goto :error
    )
    call :create_manifest || goto :error
    call :git_commit_tag_push || goto :error
    call :forgejo_release || goto :error
)

echo ========================================
echo SUCCESS! Output is in dist\%APP_NAME%.
echo ========================================
popd
exit /b 0

:read_current_version
set "CURRENT_VERSION="
for /f "tokens=2 delims==" %%A in ('findstr /b /c:"APP_VERSION" "%VERSION_FILE%"') do set "CURRENT_VERSION=%%A"
set "CURRENT_VERSION=!CURRENT_VERSION:"=!"
set "CURRENT_VERSION=!CURRENT_VERSION: =!"
if "%CURRENT_VERSION%"=="" (
    echo Failed to read APP_VERSION from %VERSION_FILE%.
    exit /b 1
)
exit /b 0

:update_version_file
%PYTHON_CMD% tools\update_version.py --path "%VERSION_FILE%" --version "%NEXT_VERSION%"
if errorlevel 1 (
    echo Failed to update %VERSION_FILE%.
    exit /b 1
)
exit /b 0

:update_changelog
%PYTHON_CMD% tools\update_changelog.py --version-tag "v%NEXT_VERSION%" --notes-file "%RELEASE_NOTES%"
if errorlevel 1 (
    echo Failed to update CHANGELOG.md.
    exit /b 1
)
exit /b 0

:compute_version_and_notes
if "%RELEASE_NOTES%"=="" set "RELEASE_NOTES=%CD%\release_notes.txt"
for /f "usebackq delims=" %%A in (`powershell -NoProfile -File "tools\release_tools.ps1" -NotesPath "%RELEASE_NOTES%"`) do set "%%A"
if "%NEXT_VERSION%"=="" (
    echo Failed to compute next version.
    exit /b 1
)
exit /b 0

:create_manifest
set "MANIFEST_PATH=%CD%\dist\%MANIFEST_NAME%"
set "DOWNLOAD_URL=https://%FORGEJO_HOST%/%FORGEJO_REPO%/releases/download/v%NEXT_VERSION%/%ZIP_NAME%"
set "EXE_PATH=%CD%\dist\%APP_NAME%\%EXE_NAME%"
set "SIGNING_THUMBPRINT_ARG="
if defined SIGN_CERT_THUMBPRINT (
    set "SIGNING_THUMBPRINT_ARG=--signing-thumbprint \"%SIGN_CERT_THUMBPRINT%\""
)
%PYTHON_CMD% tools\release_manifest.py --version "%NEXT_VERSION%" --asset-name "%ZIP_NAME%" --download-url "%DOWNLOAD_URL%" --zip-path "%ZIP_PATH%" --notes-path "%RELEASE_NOTES%" --signtool-path "%SIGNTOOL_PATH%" --exe-path "%EXE_PATH%" %SIGNING_THUMBPRINT_ARG% --output "%MANIFEST_PATH%"
if errorlevel 1 (
    echo Failed to create update manifest.
    exit /b 1
)
exit /b 0

:git_commit_tag_push
git add "%VERSION_FILE%"
git add CHANGELOG.md
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "chore(release): v%NEXT_VERSION%"
    if errorlevel 1 (
        echo Git commit failed.
        exit /b 1
    )
) else (
    echo No version change to commit.
)
git tag "v%NEXT_VERSION%"
if errorlevel 1 (
    echo Git tag failed.
    exit /b 1
)
for /f "usebackq delims=" %%B in (`git rev-parse --abbrev-ref HEAD`) do set "CURRENT_BRANCH=%%B"
if "%CURRENT_BRANCH%"=="" set "CURRENT_BRANCH=main"
git push forgejo "%CURRENT_BRANCH%"
if errorlevel 1 (
    echo Git push failed.
    exit /b 1
)
git push forgejo "v%NEXT_VERSION%"
if errorlevel 1 (
    echo Git tag push failed.
    exit /b 1
)
exit /b 0

:ensure_tracked_tree_clean
git diff --quiet
if errorlevel 1 (
    echo Working tree has uncommitted tracked changes. Commit or stash them before release.
    exit /b 1
)
git diff --cached --quiet
if errorlevel 1 (
    echo Index has staged changes. Commit or unstage them before release.
    exit /b 1
)
exit /b 0

:ensure_packageable_untracked_clean
set "FOUND_PACKAGEABLE_UNTRACKED=0"
for /f "usebackq delims=" %%F in (`git ls-files --others --exclude-standard`) do (
    set "UNTRACKED_PATH=%%F"
    set "UNTRACKED_PATH=!UNTRACKED_PATH:\=/!"
    set "IS_PACKAGEABLE=0"

    if /I "!UNTRACKED_PATH!"=="SerrebiTorrent.spec" set "IS_PACKAGEABLE=1"
    if /I "!UNTRACKED_PATH!"=="update_helper.bat" set "IS_PACKAGEABLE=1"
    if /I "!UNTRACKED_PATH!"=="icon.ico" set "IS_PACKAGEABLE=1"
    if /I "!UNTRACKED_PATH:~0,11!"=="web_static/" set "IS_PACKAGEABLE=1"
    if /I "!UNTRACKED_PATH:~0,6!"=="hooks/" set "IS_PACKAGEABLE=1"

    if "!UNTRACKED_PATH:/=!"=="!UNTRACKED_PATH!" (
        if /I "!UNTRACKED_PATH:~-3!"==".py" set "IS_PACKAGEABLE=1"
        if /I "!UNTRACKED_PATH:~-4!"==".dll" set "IS_PACKAGEABLE=1"
        if /I "!UNTRACKED_PATH:~-4!"==".pyd" set "IS_PACKAGEABLE=1"
    )

    if "!IS_PACKAGEABLE!"=="1" (
        if "!FOUND_PACKAGEABLE_UNTRACKED!"=="0" (
            echo Untracked files under packageable paths can affect the release:
        )
        echo   %%F
        set "FOUND_PACKAGEABLE_UNTRACKED=1"
    )
)
if "!FOUND_PACKAGEABLE_UNTRACKED!"=="1" (
    echo Add, ignore, or remove these files before release.
    exit /b 1
)
exit /b 0

:forgejo_release
echo Creating Forgejo release v%NEXT_VERSION%...
"%BUILD_PYTHON%" tools\forgejo_release.py --host "%FORGEJO_HOST%" --repo "%FORGEJO_REPO%" --tag "v%NEXT_VERSION%" --title "V%NEXT_VERSION%" --notes-file "%RELEASE_NOTES%" --assets "%ZIP_PATH%" "%MANIFEST_PATH%" "dist\%APP_NAME%-v%NEXT_VERSION%-linux-x86_64.tar.gz"
if errorlevel 1 (
    echo Forgejo release creation failed.
    exit /b 1
)
exit /b 0

:detect_forgejo
for /f "usebackq delims=" %%A in (`powershell -NoProfile -File "tools\get_forgejo.ps1"`) do set "%%A"
exit /b 0

:usage
echo Usage:
echo   build_exe.bat build     ^(build + sign + zip^)
echo   build_exe.bat release   ^(full release pipeline^)
echo   build_exe.bat dry-run   ^(show actions, no changes^)
exit /b 1

:error
echo ERROR: Build failed.
popd
exit /b 1

