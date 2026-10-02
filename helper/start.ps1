$ErrorActionPreference = 'Stop'

$scripts = Join-Path $PSScriptRoot '.venv\Scripts'
$python = Join-Path $scripts 'python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Helper virtual environment not found. Follow helper/README.md to install it first.'
}

$env:PATH = "$scripts;$env:PATH"

# Reuse a verified local model if one has already been downloaded for this checkout.
if (-not $env:BILI_ASR_MODEL) {
    $localModel = Join-Path (Split-Path -Parent $PSScriptRoot) '.cache\models\faster-whisper-small'
    if ((Test-Path -LiteralPath (Join-Path $localModel 'model.bin') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $localModel 'config.json') -PathType Leaf)) {
        $env:BILI_ASR_MODEL = $localModel
    }
}

& $python (Join-Path $PSScriptRoot 'server.py')
