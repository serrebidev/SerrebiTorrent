@echo off
setlocal enableextensions enabledelayedexpansion

set "APP_NAME=SerrebiTorrent"
set "EXE_NAME=SerrebiTorrent.exe"
set "VERSION_FILE=app_version.py"
set "MANIFEST_NAME=SerrebiTorrent-update.json"
set "DEFAULT_SIGNTOOL=C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe"
set "GITHUB_OWNER=serrebidev"
set "GITHUB_REPO=SerrebiTorrent"
set "PYTHON_CMD=py -3.14"

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

%PYTHON_CMD% --version >nul 2>&1 || (echo Python 3.14 not found.& goto :error)

if /I "%MODE%"=="release" (
    where git >nul 2>&1 || (echo Git not found in PATH.& goto :error)
    where gh >nul 2>&1 || (echo GitHub CLI ^(gh^) not found in PATH.& goto :error)
    call :detect_github
    call :ensure_tracked_tree_clean || goto :error
    echo Fetching tags...
    git fetch --tags
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
        echo DRY RUN: would create manifest, commit, tag, push, and create GitHub release.
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

echo Running PyInstaller...
%PYTHON_CMD% -m PyInstaller SerrebiTorrent.spec --noconfirm
if errorlevel 1 goto :error

echo Copying additional files...
copy /Y "update_helper.bat" "dist\%APP_NAME%\"
if errorlevel 1 goto :error
if exist "web_static" (
    xcopy /E /I /Y "web_static" "dist\%APP_NAME%\web_static"
    if errorlevel 1 goto :error
)

if not exist "%SIGNTOOL_PATH%" (
    echo SignTool not found: "%SIGNTOOL_PATH%"
    goto :error
)

pushd "dist\%APP_NAME%"
echo Signing %EXE_NAME%...
"%SIGNTOOL_PATH%" sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a ".\%EXE_NAME%"
if errorlevel 1 (popd & goto :error)
popd
if defined SIGN_CERT_THUMBPRINT (
    set "SIGN_CERT_THUMBPRINT=%SIGN_CERT_THUMBPRINT: =%"
)

set "ZIP_NAME=%APP_NAME%-v%NEXT_VERSION%.zip"
set "ZIP_PATH=%CD%\dist\%ZIP_NAME%"
echo Creating release ZIP: %ZIP_NAME%
powershell -NoProfile -Command "Compress-Archive -Path 'dist\%APP_NAME%' -DestinationPath '%ZIP_PATH%' -Force"
if errorlevel 1 goto :error

echo Creating latest ZIP: %APP_NAME%.zip
powershell -NoProfile -Command "Compress-Archive -Path 'dist\%APP_NAME%' -DestinationPath 'dist\%APP_NAME%.zip' -Force"

if /I "%MODE%"=="release" (
    call :create_manifest || goto :error
    call :git_commit_tag_push || goto :error
    call :gh_release || goto :error
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
set "DOWNLOAD_URL=https://github.com/%GITHUB_OWNER%/%GITHUB_REPO%/releases/download/v%NEXT_VERSION%/%ZIP_NAME%"
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
git push origin "%CURRENT_BRANCH%"
if errorlevel 1 (
    echo Git push failed.
    exit /b 1
)
git push origin "v%NEXT_VERSION%"
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

:gh_release
echo Creating GitHub release v%NEXT_VERSION%...
gh release create "v%NEXT_VERSION%" "%ZIP_PATH%" "%MANIFEST_PATH%" ^
    --title "V%NEXT_VERSION%" ^
    --notes-file "%RELEASE_NOTES%"
if errorlevel 1 (
    echo GitHub release creation failed.
    exit /b 1
)
exit /b 0

:detect_github
for /f "usebackq delims=" %%A in (`powershell -NoProfile -File "tools\get_github.ps1"`) do set "%%A"
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
