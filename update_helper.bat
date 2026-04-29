@echo off
setlocal enabledelayedexpansion

rem Always log updater output so failures aren't silent when running hidden.
for /f %%T in ('powershell -NoProfile -InputFormat None -Command "(Get-Date).ToString(\"yyyyMMddHHmmss\")"') do set "RUNSTAMP=%%T"
set "LOG_FILE=%TEMP%\SerrebiTorrent_update_!RUNSTAMP!_!RANDOM!.log"
call :main %* >> "%LOG_FILE%" 2>&1
exit /b %ERRORLEVEL%

:main
echo [SerrebiTorrent Update] Log: "%LOG_FILE%"

rem Supported argument formats:
rem   New:    update_helper.bat <pid> <install_dir> <staging_dir> <exe_name>
rem   Legacy: update_helper.bat <install_dir> <staging_dir> <backup_dir> <exe_name>

set "ARG1=%~1"
set "ARG2=%~2"
set "ARG3=%~3"
set "ARG4=%~4"

if "%ARG1%"=="" goto :usage
if "%ARG2%"=="" goto :usage
if "%ARG3%"=="" goto :usage
if "%ARG4%"=="" goto :usage

set "PID="
set "INSTALL_DIR="
set "STAGING_DIR="
set "BACKUP_DIR="
set "EXE_NAME="

rem findstr doesn't support "$" end-of-line anchor reliably; use a delimiter test instead.
set "NONNUM="
for /f "delims=0123456789" %%A in ("%ARG1%") do set "NONNUM=%%A"
if not defined NONNUM (
    set "PID=%ARG1%"
    set "INSTALL_DIR=%ARG2%"
    set "STAGING_DIR=%ARG3%"
    set "EXE_NAME=%ARG4%"
) else (
    set "INSTALL_DIR=%ARG1%"
    set "STAGING_DIR=%ARG2%"
    set "BACKUP_DIR=%ARG3%"
    set "EXE_NAME=%ARG4%"
)

if "%INSTALL_DIR%"=="" goto :usage
if "%STAGING_DIR%"=="" goto :usage
if "%EXE_NAME%"=="" goto :usage

rem Ensure we are not running from within the install directory
if not defined SERREBITORRENT_UPDATE_HELPER_RELOCATED (
    set "SCRIPT_PATH=%~f0"
    powershell -NoProfile -InputFormat None -Command "$sp=[string]$env:SCRIPT_PATH; $inst=[string]$env:INSTALL_DIR; if (-not $sp -or -not $inst) { exit 1 }; $inst=$inst.TrimEnd('\'); if ($sp.ToLower().StartsWith(($inst + '\').ToLower())) { exit 0 } else { exit 1 }" >nul 2>nul
    if not errorlevel 1 (
        set "SERREBITORRENT_UPDATE_HELPER_RELOCATED=1"
        for /f %%T in ('powershell -NoProfile -InputFormat None -Command "(Get-Date).ToString(\"yyyyMMddHHmmss\")"') do set "HSTAMP=%%T"
        set "TMP_HELPER=%TEMP%\SerrebiTorrent_update_helper_!HSTAMP!_!RANDOM!.bat"
        copy /Y "%~f0" "!TMP_HELPER!" >nul 2>nul
        if defined PID (
            start "" "!TMP_HELPER!" "%PID%" "%INSTALL_DIR%" "%STAGING_DIR%" "%EXE_NAME%"
        ) else (
            start "" "!TMP_HELPER!" "%INSTALL_DIR%" "%STAGING_DIR%" "%BACKUP_DIR%" "%EXE_NAME%"
        )
        exit /b 0
    )
)

rem Never keep the working directory inside the install folder
if exist "%TEMP%" (
    pushd "%TEMP%" >nul 2>nul
) else if exist "%SystemRoot%" (
    pushd "%SystemRoot%" >nul 2>nul
)

if not exist "%INSTALL_DIR%" (
    echo [X] Install folder not found: "%INSTALL_DIR%"
    exit /b 1
)

if not exist "%STAGING_DIR%" (
    echo [X] Staging folder not found: "%STAGING_DIR%"
    exit /b 1
)

if defined PID (
    echo [SerrebiTorrent Update] Waiting for process %PID% to exit...
    powershell -NoProfile -InputFormat None -Command "Wait-Process -Id %PID% -ErrorAction SilentlyContinue"
) else (
    echo [SerrebiTorrent Update] Waiting for %EXE_NAME% to exit...
    :wait_loop
    tasklist /FI "IMAGENAME eq %EXE_NAME%" | find /I "%EXE_NAME%" >nul
    if %errorlevel%==0 (
        echo [SerrebiTorrent Update] %EXE_NAME% is still running, attempting to kill...
        taskkill /F /IM "%EXE_NAME%" /T >nul 2>nul
        timeout /t 2 /nobreak >nul
        goto wait_loop
    )
)

rem OneDrive Fix: don't move the root folder; move CONTENTS via robocopy /MOVE.
rem Keep user data in place (portable mode): SerrebiTorrent_Data and any legacy config.json.

if not defined BACKUP_DIR (
    for /f %%T in ('powershell -NoProfile -InputFormat None -Command "(Get-Date).ToString(\"yyyyMMddHHmmss\")"') do set STAMP=%%T
    set "BACKUP_DIR=%INSTALL_DIR%_backup_!STAMP!"
)

echo [SerrebiTorrent Update] Backing up current install to "%BACKUP_DIR%"...
if exist "%BACKUP_DIR%" rmdir /s /q "%BACKUP_DIR%" >nul 2>nul
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%" >nul 2>nul

robocopy "%INSTALL_DIR%" "%BACKUP_DIR%" /E /MOVE /R:3 /W:1 /NFL /NDL /XD SerrebiTorrent_Data .git .venv __pycache__ /XF config.json
set "RC=%ERRORLEVEL%"
if %RC% geq 8 (
    echo [X] Backup failed with robocopy code %RC%.
    goto :rollback
)

echo [SerrebiTorrent Update] Applying update...
robocopy "%STAGING_DIR%" "%INSTALL_DIR%" /E /MOVE /R:3 /W:1 /NFL /NDL /XD SerrebiTorrent_Data .git .venv __pycache__ /XF config.json
set "RC=%ERRORLEVEL%"
if %RC% geq 8 (
    echo [X] Update application failed with robocopy code %RC%.
    goto :rollback
)

echo [SerrebiTorrent Update] Cleaning up staging folder...
if exist "%STAGING_DIR%" (
    rmdir /s /q "%STAGING_DIR%" >nul 2>nul
)
call :cleanup_staging_root "%STAGING_DIR%"

rem Handle backup cleanup based on retention policy
set "KEEP_BACKUPS=%SERREBITORRENT_KEEP_BACKUPS%"
if not defined KEEP_BACKUPS set "KEEP_BACKUPS=1"

echo [SerrebiTorrent Update] Backup retention policy: keep %KEEP_BACKUPS% backup(s)

rem Simplified backup cleanup logic
if /i "%KEEP_BACKUPS%"=="0" (
    echo [SerrebiTorrent Update] Deleting backup immediately retention=0...
    if exist "%BACKUP_DIR%" rmdir /s /q "%BACKUP_DIR%" >nul 2>&1
    if exist "%BACKUP_DIR%" (
        echo [SerrebiTorrent Update] WARNING: Backup folder still exists after delete attempt
    )
) else (
    rem Schedule backup cleanup after 5-minute grace period, then enforce retention
    call :schedule_backup_cleanup "%BACKUP_DIR%" "%INSTALL_DIR%" "%KEEP_BACKUPS%" "%STAGING_DIR%"
)

echo [SerrebiTorrent Update] Launching app...
rem Use VBScript for invisible app launch
set "VBS_LAUNCHER=%TEMP%\SerrebiTorrent_launch_!RUNSTAMP!_!RANDOM!.vbs"
echo Set WshShell = CreateObject("WScript.Shell") > "%VBS_LAUNCHER%"
echo On Error Resume Next >> "%VBS_LAUNCHER%"
echo WshShell.Run Chr(34) ^& "%INSTALL_DIR%\%EXE_NAME%" ^& Chr(34), 0, False >> "%VBS_LAUNCHER%"
echo Set WshShell = Nothing >> "%VBS_LAUNCHER%"
wscript.exe //nologo "%VBS_LAUNCHER%" >nul 2>nul
del "%VBS_LAUNCHER%" >nul 2>nul
exit /b 0

:rollback
echo [SerrebiTorrent Update] Update failed. Restoring backup...
if exist "%BACKUP_DIR%" (
    robocopy "%BACKUP_DIR%" "%INSTALL_DIR%" /E /MOVE /R:3 /W:1 /NFL /NDL /XD SerrebiTorrent_Data /XF config.json
)
rem Use VBScript for invisible app launch
set "VBS_LAUNCHER=%TEMP%\SerrebiTorrent_launch_!RUNSTAMP!_!RANDOM!.vbs"
echo Set WshShell = CreateObject("WScript.Shell") > "%VBS_LAUNCHER%"
echo On Error Resume Next >> "%VBS_LAUNCHER%"
echo WshShell.Run Chr(34) ^& "%INSTALL_DIR%\%EXE_NAME%" ^& Chr(34), 0, False >> "%VBS_LAUNCHER%"
echo Set WshShell = Nothing >> "%VBS_LAUNCHER%"
wscript.exe //nologo "%VBS_LAUNCHER%" >nul 2>nul
del "%VBS_LAUNCHER%" >nul 2>nul
powershell -NoProfile -InputFormat None -Command "param([string]$log) try { Add-Type -AssemblyName PresentationFramework | Out-Null; $msg = 'SerrebiTorrent update failed.' + \"`n`n\" + 'Log file:' + \"`n\" + $log; [System.Windows.MessageBox]::Show($msg, 'SerrebiTorrent Update', 'OK', 'Error') | Out-Null } catch { }" "%LOG_FILE%" >nul 2>nul
exit /b 1

:cleanup_staging_root
set "CLEANUP_STAGING_DIR=%~1"
if "%CLEANUP_STAGING_DIR%"=="" exit /b 0
for %%D in ("%CLEANUP_STAGING_DIR%\..") do set "STAGING_ROOT=%%~fD"
if "%STAGING_ROOT%"=="" exit /b 0
if not exist "%STAGING_ROOT%" exit /b 0

set "SCRIPT_PATH=%~f0"
powershell -NoProfile -InputFormat None -Command "$sp=[string]$env:SCRIPT_PATH; $root=[string]$env:STAGING_ROOT; if (-not $sp -or -not $root) { exit 1 }; $root=$root.TrimEnd('\'); if ($sp.ToLower().StartsWith(($root + '\').ToLower())) { exit 0 } else { exit 1 }" >nul 2>nul
if errorlevel 1 (
    rmdir /s /q "%STAGING_ROOT%" >nul 2>nul
) else (
    call :schedule_staging_root_cleanup "%STAGING_ROOT%"
)
exit /b 0

:schedule_staging_root_cleanup
set "STAGING_ROOT_TO_DELETE=%~1"
if "%STAGING_ROOT_TO_DELETE%"=="" exit /b 0
for /f %%T in ('powershell -NoProfile -InputFormat None -Command "(Get-Date).ToString(\"yyyyMMddHHmmss\")"') do set "STAGESTAMP=%%T"
set "STAGING_CLEANUP_SCRIPT=%TEMP%\SerrebiTorrent_staging_cleanup_!STAGESTAMP!_!RANDOM!.bat"

echo @echo off > "%STAGING_CLEANUP_SCRIPT%"
echo timeout /t 2 /nobreak ^>nul 2^>nul >> "%STAGING_CLEANUP_SCRIPT%"
echo rmdir /s /q "%STAGING_ROOT_TO_DELETE%" ^>nul 2^>nul >> "%STAGING_CLEANUP_SCRIPT%"
echo del "%%~f0" ^>nul 2^>nul >> "%STAGING_CLEANUP_SCRIPT%"
powershell -WindowStyle Hidden -NoProfile -Command "Start-Process -FilePath cmd.exe -ArgumentList '/c','\"%STAGING_CLEANUP_SCRIPT%\"' -WindowStyle Hidden" >nul 2>nul
exit /b 0

:schedule_backup_cleanup
rem Schedule cleanup of old backups and staging folder
set "CLEANUP_BACKUP=%~1"
set "CLEANUP_INSTALL=%~2"
set "CLEANUP_KEEP=%~3"
set "CLEANUP_STAGING=%~4"

rem Create cleanup script in TEMP
for /f %%T in ('powershell -NoProfile -InputFormat None -Command "(Get-Date).ToString(\"yyyyMMddHHmmss\")"') do set "CLEANSTAMP=%%T"
set "CLEANUP_SCRIPT=%TEMP%\SerrebiTorrent_cleanup_!CLEANSTAMP!_!RANDOM!.bat"

echo @echo off > "%CLEANUP_SCRIPT%"
echo rem Auto-cleanup script for SerrebiTorrent backups >> "%CLEANUP_SCRIPT%"
echo set "CLEANUP_KEEP=%CLEANUP_KEEP%" >> "%CLEANUP_SCRIPT%"
echo set "CLEANUP_STAGING=%CLEANUP_STAGING%" >> "%CLEANUP_SCRIPT%"
echo timeout /t 300 /nobreak ^>nul 2^>nul >> "%CLEANUP_SCRIPT%"
echo. >> "%CLEANUP_SCRIPT%"
echo rem Clean up the just-created backup after grace period >> "%CLEANUP_SCRIPT%"
echo if exist "%CLEANUP_BACKUP%" ( >> "%CLEANUP_SCRIPT%"
echo     rmdir /s /q "%CLEANUP_BACKUP%" ^>nul 2^>nul >> "%CLEANUP_SCRIPT%"
echo ) >> "%CLEANUP_SCRIPT%"
echo. >> "%CLEANUP_SCRIPT%"
echo rem Enforce backup retention policy >> "%CLEANUP_SCRIPT%"
echo for %%%%D in ("%CLEANUP_INSTALL%\.."^) do set "PARENT=%%%%~fD" >> "%CLEANUP_SCRIPT%"
echo powershell -NoProfile -InputFormat None -Command "$parent=$env:PARENT; $keep=[int]$env:CLEANUP_KEEP; $pattern='*_backup_*'; $backups=@(Get-ChildItem -Path $parent -Directory ^| Where-Object { $_.Name -like $pattern } ^| Sort-Object Name -Descending); if ($backups.Count -gt $keep) { $backups ^| Select-Object -Skip $keep ^| ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue } }" >> "%CLEANUP_SCRIPT%"
echo. >> "%CLEANUP_SCRIPT%"
echo rem Clean up staging root folder >> "%CLEANUP_SCRIPT%"
echo if defined CLEANUP_STAGING ( >> "%CLEANUP_SCRIPT%"
echo     for %%%%D in ("%CLEANUP_STAGING%\.."^) do set "STAGING_ROOT=%%%%~fD" >> "%CLEANUP_SCRIPT%"
echo     if exist "%%STAGING_ROOT%%" rmdir /s /q "%%STAGING_ROOT%%" ^>nul 2^>nul >> "%CLEANUP_SCRIPT%"
echo ) >> "%CLEANUP_SCRIPT%"
echo. >> "%CLEANUP_SCRIPT%"
echo rem Self-destruct >> "%CLEANUP_SCRIPT%"
echo del "%%~f0" ^>nul 2^>nul >> "%CLEANUP_SCRIPT%"

rem Launch cleanup script detached and hidden
powershell -WindowStyle Hidden -NoProfile -Command "Start-Process -FilePath cmd.exe -ArgumentList '/c','\"%CLEANUP_SCRIPT%\"' -WindowStyle Hidden" >nul 2>nul
exit /b 0

:usage
echo Usage: update_helper.bat ^<pid^> ^<install_dir^> ^<staging_dir^> ^<exe_name^>
echo    or: update_helper.bat ^<install_dir^> ^<staging_dir^> ^<backup_dir^> ^<exe_name^>  (legacy)
exit /b 1
