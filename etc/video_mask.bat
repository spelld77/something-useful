@echo off
setlocal
cd /d "%~dp0"
set "SELF=%~f0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$p=$env:SELF; $m=('###'+'POWERSHELL'+'###'); $t=[System.IO.File]::ReadAllText($p); $i=$t.IndexOf($m,[System.StringComparison]::Ordinal); if($i -lt 0){Write-Host 'ERROR: PowerShell marker not found.'; exit 2}; $s=$t.Substring($i+$m.Length); & ([ScriptBlock]::Create($s))"

set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%


###POWERSHELL###

$ErrorActionPreference = 'Stop'

# ============================================================
# SETTINGS
# ============================================================

$Base = (Get-Location).Path
$MapFile = Join-Path $Base 'video_restore_map.json'

$VideoExtensions = @(
    '.mp4',
    '.mkv',
    '.avi',
    '.mov',
    '.wmv',
    '.webm',
    '.m4v',
    '.ts',
    '.mts',
    '.m2ts',
    '.flv',
    '.mpg',
    '.mpeg',
    '.vob'
)


# ============================================================
# COMMON FUNCTIONS
# ============================================================

function Get-RelativePath {

    param(
        [string]$FullPath
    )

    $relative = $FullPath.Substring($Base.Length)

    if ($relative.StartsWith('\')) {
        $relative = $relative.Substring(1)
    }

    return $relative
}


function Get-IsHidden {

    param(
        $Item
    )

    return [bool](
        ($Item.Attributes -band [IO.FileAttributes]::Hidden) -ne 0
    )
}


function Set-HiddenFlag {

    param(
        [string]$Path,
        [bool]$Hidden
    )

    $item = Get-Item -LiteralPath $Path -Force

    if ($Hidden) {

        $item.Attributes = [IO.FileAttributes](
            $item.Attributes -bor
            [IO.FileAttributes]::Hidden
        )

    }
    else {

        $item.Attributes = [IO.FileAttributes](
            $item.Attributes -band
            (-bnot [IO.FileAttributes]::Hidden)
        )
    }
}


function New-RandomName {

    param(
        [string]$Parent
    )

    do {

        $name = [guid]::NewGuid().ToString('N')
        $candidate = Join-Path $Parent $name

    }
    while (
        Test-Path -LiteralPath $candidate
    )

    return $name
}


function Save-Map {

    param(
        $Map
    )

    $Map.Updated = (Get-Date).ToString('o')

    $json = $Map | ConvertTo-Json -Depth 10

    $encoding =
        New-Object System.Text.UTF8Encoding($false)

    [IO.File]::WriteAllText(
        $MapFile,
        $json,
        $encoding
    )
}


function Load-Map {

    if (-not (Test-Path -LiteralPath $MapFile)) {
        return $null
    }

    $encoding =
        New-Object System.Text.UTF8Encoding($false)

    $json =
        [IO.File]::ReadAllText(
            $MapFile,
            $encoding
        )

    return (
        ConvertFrom-Json -InputObject $json
    )
}


function Get-CurrentStatus {

    if (-not (Test-Path -LiteralPath $MapFile)) {
        return 'NORMAL'
    }

    try {

        $map = Load-Map

        if ($map.State -eq 'IN_PROGRESS') {
            return "IN_PROGRESS -> $($map.Mode)"
        }

        return [string]$map.State

    }
    catch {

        return 'MAP ERROR'
    }
}


function Wait-Key {

    Write-Host ''
    [void](Read-Host 'Press ENTER to continue')
}


# ============================================================
# RANDOMIZE
# ============================================================

function Invoke-Randomize {

    param(
        [bool]$Hide
    )


    # --------------------------------------------------------
    # Existing map check
    # --------------------------------------------------------

    if (Test-Path -LiteralPath $MapFile) {

        throw 'Recovery map already exists. Restore first.'
    }


    # --------------------------------------------------------
    # Get video files
    # --------------------------------------------------------

    $allFiles = @(
        Get-ChildItem `
            -LiteralPath $Base `
            -Recurse `
            -File `
            -Force
    )


    $videoFiles = @(
        foreach ($file in $allFiles) {

            if (
                $VideoExtensions -contains
                $file.Extension.ToLowerInvariant()
            ) {

                $file
            }
        }
    )


    if ($videoFiles.Count -eq 0) {

        throw 'No video files found.'
    }


    # --------------------------------------------------------
    # Get subdirectories
    # --------------------------------------------------------

    $allDirectories = @(
        Get-ChildItem `
            -LiteralPath $Base `
            -Recurse `
            -Directory `
            -Force
    )


    $directories = @(
        foreach ($directory in $allDirectories) {

            if (
                -not (
                    $directory.Attributes -band
                    [IO.FileAttributes]::ReparsePoint
                )
            ) {

                $directory
            }
        }
    )


    # --------------------------------------------------------
    # Build FILE map
    # --------------------------------------------------------

    $fileData = @(

        foreach ($file in $videoFiles) {

            $temporaryName =
                New-RandomName `
                    -Parent $file.DirectoryName


            [pscustomobject]@{

                OriginalPath =
                    Get-RelativePath $file.FullName

                TemporaryName =
                    $temporaryName

                OriginalHidden =
                    Get-IsHidden $file
            }
        }
    )


    # --------------------------------------------------------
    # Build DIRECTORY map
    # --------------------------------------------------------

    $directoryData = @(

        foreach ($directory in $directories) {

            $temporaryName =
                New-RandomName `
                    -Parent $directory.Parent.FullName


            $relative =
                Get-RelativePath $directory.FullName


            $depth =
                ($relative -split '\\').Count


            [pscustomobject]@{

                OriginalPath =
                    $relative

                TemporaryName =
                    $temporaryName

                OriginalHidden =
                    Get-IsHidden $directory

                Depth =
                    $depth
            }
        }
    )


    # --------------------------------------------------------
    # Mode
    # --------------------------------------------------------

    if ($Hide) {

        $mode = 'RANDOMIZED_HIDDEN'

    }
    else {

        $mode = 'RANDOMIZED'
    }


    # --------------------------------------------------------
    # SAVE MAP FIRST
    # --------------------------------------------------------

    $map = [pscustomobject][ordered]@{

        Version = 1

        State =
            'IN_PROGRESS'

        Mode =
            $mode

        Created =
            (Get-Date).ToString('o')

        Updated =
            (Get-Date).ToString('o')

        Files =
            @($fileData)

        Directories =
            @($directoryData)
    }


    Save-Map $map


    # --------------------------------------------------------
    # Rename VIDEO FILES
    # --------------------------------------------------------

    foreach ($item in $fileData) {

        $source =
            Join-Path `
                $Base `
                $item.OriginalPath


        if (-not (Test-Path -LiteralPath $source)) {

            throw "Missing file: $($item.OriginalPath)"
        }


        $parent =
            [IO.Path]::GetDirectoryName(
                $source
            )


        Rename-Item `
            -LiteralPath $source `
            -NewName $item.TemporaryName


        $temporaryPath =
            Join-Path `
                $parent `
                $item.TemporaryName


        if ($Hide) {

            Set-HiddenFlag `
                -Path $temporaryPath `
                -Hidden $true
        }
    }


    # --------------------------------------------------------
    # Rename DIRECTORIES
    #
    # Deepest first
    # --------------------------------------------------------

    if ($directoryData.Count -gt 0) {

        $maxDepth = 0

        foreach ($item in $directoryData) {

            if ([int]$item.Depth -gt $maxDepth) {

                $maxDepth =
                    [int]$item.Depth
            }
        }


        for (
            $depth = $maxDepth;
            $depth -ge 1;
            $depth--
        ) {

            foreach ($item in $directoryData) {

                if (
                    [int]$item.Depth -ne $depth
                ) {
                    continue
                }


                $source =
                    Join-Path `
                        $Base `
                        $item.OriginalPath


                if (
                    Test-Path -LiteralPath $source
                ) {

                    $parent =
                        [IO.Path]::GetDirectoryName(
                            $source
                        )


                    Rename-Item `
                        -LiteralPath $source `
                        -NewName $item.TemporaryName


                    $temporaryPath =
                        Join-Path `
                            $parent `
                            $item.TemporaryName


                    if ($Hide) {

                        Set-HiddenFlag `
                            -Path $temporaryPath `
                            -Hidden $true
                    }
                }
            }
        }
    }


    # --------------------------------------------------------
    # Finished
    # --------------------------------------------------------

    $map.State = $mode

    Save-Map $map


    Write-Host ''
    Write-Host '========================================'
    Write-Host ' COMPLETED'
    Write-Host '========================================'
    Write-Host ''
    Write-Host "Video files : $($fileData.Count)"
    Write-Host "Folders     : $($directoryData.Count)"
    Write-Host "Mode        : $mode"
    Write-Host ''
    Write-Host 'DO NOT DELETE video_restore_map.json'
}


# ============================================================
# RESTORE
# ============================================================

function Invoke-Restore {

    $map = Load-Map


    if ($null -eq $map) {

        throw 'video_restore_map.json not found.'
    }


    $files =
        @($map.Files)


    $directories =
        @($map.Directories)


    $errors = 0


    # --------------------------------------------------------
    # Restore DIRECTORIES
    #
    # Shallowest first
    # --------------------------------------------------------

    if ($directories.Count -gt 0) {

        $maxDepth = 0

        foreach ($item in $directories) {

            if ([int]$item.Depth -gt $maxDepth) {

                $maxDepth =
                    [int]$item.Depth
            }
        }


        for (
            $depth = 1;
            $depth -le $maxDepth;
            $depth++
        ) {

            foreach ($item in $directories) {

                if (
                    [int]$item.Depth -ne $depth
                ) {
                    continue
                }


                $parentRelative =
                    [IO.Path]::GetDirectoryName(
                        [string]$item.OriginalPath
                    )


                $originalName =
                    [IO.Path]::GetFileName(
                        [string]$item.OriginalPath
                    )


                if (
                    [string]::IsNullOrEmpty(
                        $parentRelative
                    )
                ) {

                    $parent =
                        $Base

                }
                else {

                    $parent =
                        Join-Path `
                            $Base `
                            $parentRelative
                }


                $temporaryPath =
                    Join-Path `
                        $parent `
                        ([string]$item.TemporaryName)


                $originalPath =
                    Join-Path `
                        $parent `
                        $originalName


                $temporaryExists =
                    Test-Path `
                        -LiteralPath $temporaryPath


                $originalExists =
                    Test-Path `
                        -LiteralPath $originalPath


                # Both exist
                if (
                    $temporaryExists -and
                    $originalExists
                ) {

                    Write-Host "CONFLICT: $originalPath"

                    $errors++

                    continue
                }


                # Randomized folder exists
                if ($temporaryExists) {

                    try {

                        Set-HiddenFlag `
                            -Path $temporaryPath `
                            -Hidden $false


                        Rename-Item `
                            -LiteralPath $temporaryPath `
                            -NewName $originalName


                        Set-HiddenFlag `
                            -Path $originalPath `
                            -Hidden ([bool]$item.OriginalHidden)

                    }
                    catch {

                        Write-Host "ERROR: $temporaryPath"

                        $errors++
                    }

                    continue
                }


                # Already restored
                if ($originalExists) {

                    try {

                        Set-HiddenFlag `
                            -Path $originalPath `
                            -Hidden ([bool]$item.OriginalHidden)

                    }
                    catch {

                        Write-Host "ERROR: $originalPath"

                        $errors++
                    }

                    continue
                }


                Write-Host "MISSING: $($item.OriginalPath)"

                $errors++
            }
        }
    }


    # --------------------------------------------------------
    # Restore VIDEO FILES
    # --------------------------------------------------------

    foreach ($item in $files) {

        $originalPath =
            Join-Path `
                $Base `
                ([string]$item.OriginalPath)


        $parent =
            [IO.Path]::GetDirectoryName(
                $originalPath
            )


        $originalName =
            [IO.Path]::GetFileName(
                $originalPath
            )


        $temporaryPath =
            Join-Path `
                $parent `
                ([string]$item.TemporaryName)


        $temporaryExists =
            Test-Path `
                -LiteralPath $temporaryPath


        $originalExists =
            Test-Path `
                -LiteralPath $originalPath


        # Both exist
        if (
            $temporaryExists -and
            $originalExists
        ) {

            Write-Host "CONFLICT: $originalPath"

            $errors++

            continue
        }


        # Randomized file exists
        if ($temporaryExists) {

            try {

                Set-HiddenFlag `
                    -Path $temporaryPath `
                    -Hidden $false


                Rename-Item `
                    -LiteralPath $temporaryPath `
                    -NewName $originalName


                Set-HiddenFlag `
                    -Path $originalPath `
                    -Hidden ([bool]$item.OriginalHidden)

            }
            catch {

                Write-Host "ERROR: $temporaryPath"

                $errors++
            }

            continue
        }


        # Already restored
        if ($originalExists) {

            try {

                Set-HiddenFlag `
                    -Path $originalPath `
                    -Hidden ([bool]$item.OriginalHidden)

            }
            catch {

                Write-Host "ERROR: $originalPath"

                $errors++
            }

            continue
        }


        Write-Host "MISSING: $($item.OriginalPath)"

        $errors++
    }


    # --------------------------------------------------------
    # Cleanup
    # --------------------------------------------------------

    if ($errors -eq 0) {

        Remove-Item `
            -LiteralPath $MapFile `
            -Force


        Write-Host ''
        Write-Host '========================================'
        Write-Host ' RESTORE COMPLETED'
        Write-Host '========================================'
        Write-Host ''
        Write-Host 'All names were restored.'
        Write-Host 'Recovery map was removed.'

    }
    else {

        Write-Host ''
        Write-Host '========================================'
        Write-Host ' RESTORE INCOMPLETE'
        Write-Host '========================================'
        Write-Host ''
        Write-Host "Errors : $errors"
        Write-Host ''
        Write-Host 'Recovery map was NOT deleted.'
    }
}


# ============================================================
# STATUS
# ============================================================

function Show-Status {

    Clear-Host

    Write-Host '========================================'
    Write-Host ' STATUS'
    Write-Host '========================================'
    Write-Host ''


    if (
        -not (
            Test-Path -LiteralPath $MapFile
        )
    ) {

        Write-Host 'State : NORMAL'
        Write-Host ''

        return
    }


    try {

        $map =
            Load-Map


        Write-Host "State : $($map.State)"
        Write-Host "Mode  : $($map.Mode)"
        Write-Host "Files : $(@($map.Files).Count)"
        Write-Host "Dirs  : $(@($map.Directories).Count)"
        Write-Host ''

    }
    catch {

        Write-Host 'State : MAP ERROR'
        Write-Host ''
        Write-Host $_.Exception.Message
        Write-Host ''
    }
}


# ============================================================
# MAIN MENU
# ============================================================

while ($true) {

    Clear-Host

    $status =
        Get-CurrentStatus


    Write-Host '========================================'
    Write-Host ' VIDEO TEMP RENAME TOOL'
    Write-Host '========================================'
    Write-Host ''
    Write-Host " Current status : $status"
    Write-Host ''
    Write-Host ' 1. Randomize'
    Write-Host ' 2. Randomize + Hide'
    Write-Host ' 3. Restore'
    Write-Host ' 4. Status'
    Write-Host ' 0. Exit'
    Write-Host ''


    $choice =
        Read-Host 'Select'


    switch ($choice) {

        '1' {

            try {

                Invoke-Randomize `
                    -Hide $false

            }
            catch {

                Write-Host ''
                Write-Host "ERROR: $($_.Exception.Message)"
            }

            Wait-Key
        }


        '2' {

            try {

                Invoke-Randomize `
                    -Hide $true

            }
            catch {

                Write-Host ''
                Write-Host "ERROR: $($_.Exception.Message)"
            }

            Wait-Key
        }


        '3' {

            try {

                Invoke-Restore

            }
            catch {

                Write-Host ''
                Write-Host "ERROR: $($_.Exception.Message)"
            }

            Wait-Key
        }


        '4' {

            Show-Status
            Wait-Key
        }


        '0' {

            break
        }
    }
}