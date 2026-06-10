@echo off
chcp 65001 >nul 2>&1
setlocal
rem Запуск генератора подставки для свёрел через freecadcmd (Windows, cmd/PowerShell).
rem   drill-holder.cmd [config.py] [--no-gui]
rem По умолчанию открывается Qt-диалог правки; --no-gui — собрать сразу по конфигу.
rem Путь к freecadcmd можно задать переменной окружения FREECADCMD.

set "HERE=%~dp0"
set "FCMD="

rem 1) Явно заданный путь FREECADCMD (файл или имя в PATH).
if defined FREECADCMD (
  if exist "%FREECADCMD%" (
    set "FCMD=%FREECADCMD%"
  ) else (
    for /f "delims=" %%P in ('where "%FREECADCMD%" 2^>nul') do if not defined FCMD set "FCMD=%%P"
  )
  if not defined FCMD (
    echo Ошибка: FREECADCMD='%FREECADCMD%' не найден или не исполняем.>&2
    exit /b 1
  )
)

rem 2) В PATH.
if not defined FCMD (
  for %%N in (freecadcmd.exe FreeCADCmd.exe freecadcmd FreeCADCmd) do (
    if not defined FCMD for /f "delims=" %%P in ('where %%N 2^>nul') do if not defined FCMD set "FCMD=%%P"
  )
)

rem 3) Типовые места установки — свежайшая версия каталога FreeCAD*.
if not defined FCMD (
  for %%R in ("%ProgramFiles%" "%ProgramFiles(x86)%" "%LOCALAPPDATA%\Programs") do (
    if not defined FCMD if exist "%%~R" (
      for /f "delims=" %%D in ('dir /b /ad /o-n "%%~R\FreeCAD*" 2^>nul') do (
        if not defined FCMD if exist "%%~R\%%D\bin\freecadcmd.exe" set "FCMD=%%~R\%%D\bin\freecadcmd.exe"
      )
    )
  )
)

if not defined FCMD (
  echo Ошибка: не найден freecadcmd. Установите FreeCAD 1.0+ или задайте FREECADCMD.>&2
  exit /b 1
)

rem '--' отделяет аргументы скрипта: freecadcmd сам перехватывает --gui/--no-gui и пути,
rem всё после '--' отдаёт build_holder.py дословно.
"%FCMD%" "%HERE%build_holder.py" -- %*
exit /b %ERRORLEVEL%
