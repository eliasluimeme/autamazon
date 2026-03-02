# Check if the script is being sourced or executed
(return 0 2>/dev/null) && IS_SOURCED=true || IS_SOURCED=false

# 1. Run the python setup logic
python3 setup.py --no-shell

# 2. Source the virtual environment in the CURRENT shell
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    
    if [ "$IS_SOURCED" = true ]; then
        echo "✅ SUCCESS: .venv is now active in THIS SHELL."
    else
        echo ""
        echo "⚠️  WARNING: You executed this script directly (./setup.sh)."
        echo "⚠️  The venv is active INSIDE the script, but will NOT persist in your current terminal."
        echo "⚠️  Fix: ALWAYS run with 'source' like this:"
        echo ""
        echo "    source ./setup.sh"
        echo ""
    fi
    PYTHON_PATH=$(which python)
    echo "Python: $PYTHON_PATH"
else
    echo "❌ ERROR: Virtual environment not found. Setup may have failed."
fi
