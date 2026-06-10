# Запуск генератора подставки для свёрел через freecadcmd (Windows PowerShell / pwsh).
#
#   .\drill-holder.ps1 [config.py] [--no-gui]
#
# По умолчанию открывается Qt-диалог разовой правки (freecadcmd поднимает своё окно).
# --no-gui — собрать сразу по конфигу, без диалога. Без аргументов берётся holder_config.py
# рядом со скриптом. Путь к freecadcmd можно задать переменной окружения $env:FREECADCMD.
$ErrorActionPreference = 'Stop'

function Find-FreeCADCmd {
    # 1) Явно заданный путь (файл или имя в PATH).
    if ($env:FREECADCMD) {
        if (Test-Path -LiteralPath $env:FREECADCMD) { return $env:FREECADCMD }
        $c = Get-Command $env:FREECADCMD -ErrorAction SilentlyContinue
        if ($c) { return $c.Source }
        throw "FREECADCMD='$($env:FREECADCMD)' не найден или не исполняем."
    }
    # 2) В PATH.
    foreach ($name in 'freecadcmd.exe', 'FreeCADCmd.exe', 'freecadcmd', 'FreeCADCmd') {
        $c = Get-Command $name -ErrorAction SilentlyContinue
        if ($c) { return $c.Source }
    }
    # 3) Типовые места установки — свежайшая версия каталога FreeCAD*.
    $roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, (Join-Path $env:LOCALAPPDATA 'Programs')) |
        Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    foreach ($root in $roots) {
        $dir = Get-ChildItem -LiteralPath $root -Directory -Filter 'FreeCAD*' -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'bin\freecadcmd.exe') } |
            Select-Object -First 1
        if ($dir) { return (Join-Path $dir.FullName 'bin\freecadcmd.exe') }
    }
    return $null
}

$fcmd = Find-FreeCADCmd
if (-not $fcmd) {
    Write-Error @'
не найден freecadcmd.
Установите FreeCAD (1.0+) или укажите путь явно, например:
  $env:FREECADCMD = 'C:\Program Files\FreeCAD 1.0\bin\freecadcmd.exe'; .\drill-holder.ps1 --no-gui
'@
    exit 1
}

# '--' отделяет аргументы скрипта: freecadcmd сам перехватывает --gui/--no-gui и пути-аргументы,
# а всё после '--' отдаёт build_holder.py дословно (тот снимает ведущий '--' из argv).
& $fcmd (Join-Path $PSScriptRoot 'build_holder.py') '--' @args
exit $LASTEXITCODE
