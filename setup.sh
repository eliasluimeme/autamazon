# Check if the script is being sourced or executed
(return 0 2>/dev/null) && IS_SOURCED=true || IS_SOURCED=false

# 1. Deactivate any active venv so we run setup with the real system Python.
#    This prevents sys.executable from pointing at a soon-to-be-deleted venv.
if [ -n "$VIRTUAL_ENV" ]; then
    echo "[INFO] Deactivating active virtual environment before setup..."
    deactivate 2>/dev/null || true
fi

# Prefer the py launcher or first python3 that is NOT inside our .venv
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_BIN="$SCRIPT_DIR/.venv/bin"

PYTHON_CMD=""
for candidate in python3 python; do
    _path="$(command -v $candidate 2>/dev/null)"
    if [ -n "$_path" ] && [[ "$_path" != "$VENV_BIN"* ]]; then
        PYTHON_CMD="$_path"
        break
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "ERROR: No system Python 3 found outside the venv. Please install Python 3.8+."
    return 1 2>/dev/null || exit 1
fi

echo "[INFO] Using system Python: $PYTHON_CMD"

# 2. Run the python setup logic
"$PYTHON_CMD" setup.py --no-shell

# 3. Source the virtual environment in the CURRENT shell
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    
    if [ "$IS_SOURCED" = true ]; then
        echo "SUCCESS: .venv is now active in THIS SHELL."
    else
        echo ""
        echo "WARNING: You executed this script directly (./setup.sh)."
        echo "WARNING: The venv is active INSIDE the script, but will NOT persist in your current terminal."
        echo "WARNING: Fix: ALWAYS run with 'source' like this:"
        echo ""
        echo "    source ./setup.sh"
        echo ""
    fi
    PYTHON_PATH=$(which python)
    echo "Python: $PYTHON_PATH"
else
    echo "ERROR: Virtual environment not found. Setup may have failed."
fi
