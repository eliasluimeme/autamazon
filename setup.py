import subprocess
import os
import sys
import shutil
import platform

def run_command(command, shell=False):
    """Run a system command and exit on failure."""
    print(f"\n[INFO] Executing: {' '.join(command) if isinstance(command, list) else command}")
    try:
        # On Windows, we need shell=True for some commands if they are not absolute paths
        # but subprocess.check_call works well with list on both if executable is found
        subprocess.check_call(command, shell=shell)
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Command failed with exit code {e.returncode}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"\n[ERROR] Could not find executable for command: {command}")
        sys.exit(1)

def clean_project():
    """Remove temporary files and caches."""
    print("\n[INFO] Cleaning project artifacts...")
    
    # Remove __pycache__ directories
    for root, dirs, files in os.walk("."):
        if "__pycache__" in dirs:
            pycache_path = os.path.join(root, "__pycache__")
            print(f"  Removing {pycache_path}")
            shutil.rmtree(pycache_path)
            
    # Remove .venv if it exists (though the script might have been called to recreate it)
    if os.path.exists(".venv"):
        print("  Removing existing .venv...")
        shutil.rmtree(".venv")

def setup_venv():
    """Create and return paths for virtual environment."""
    print("\n[INFO] Creating virtual environment...")
    python_cmd = sys.executable
    run_command([python_cmd, "-m", "venv", ".venv"])
    
    if platform.system() == "Windows":
        venv_python = os.path.join(".venv", "Scripts", "python.exe")
        venv_pip = os.path.join(".venv", "Scripts", "pip.exe")
    else:
        venv_python = os.path.join(".venv", "bin", "python")
        venv_pip = os.path.join(".venv", "bin", "pip")
        
    return venv_python, venv_pip

def install_dependencies(venv_python):
    """Install requirements and browser binaries."""
    print("\n[INFO] Upgrading pip and setuptools...")
    run_command([venv_python, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    
    if os.path.exists("requirements.txt"):
        print("\n[INFO] Installing dependencies from requirements.txt...")
        # Use python -m pip for better reliability across different shell environments
        run_command([venv_python, "-m", "pip", "install", "-r", "requirements.txt"])
    else:
        print("\n[WARNING] requirements.txt not found. Skipping dependency installation.")

    # Verification Step
    print("\n[INFO] Verifying critical packages...")
    critical_pkgs = ["playwright", "agentql", "patchright", "loguru"]
    missing = []
    for pkg in critical_pkgs:
        try:
            subprocess.check_call([venv_python, "-c", f"import {pkg}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            missing.append(pkg)
    
    if missing:
        print(f"  ⚠️ Missing packages: {', '.join(missing)}. Force-installing...")
        run_command([venv_python, "-m", "pip", "install"] + missing)
    else:
        print("  ✅ All critical packages (playwright, agentql, patchright, loguru) are present.")

    print("\n[INFO] Installing Playwright browser binaries...")
    run_command([venv_python, "-m", "playwright", "install", "chromium"])

def setup_env_file():
    """Initialize .env file if it doesn't exist."""
    print("\n[INFO] Checking environment configuration...")
    if not os.path.exists(".env"):
        if os.path.exists(".env.example"):
            print("  Creating .env from .env.example...")
            shutil.copy(".env.example", ".env")
            print("  Created .env. PLEASE UPDATE IT WITH YOUR ACTUAL CREDENTIALS!")
        else:
            print("  [WARNING] Neither .env nor .env.example found. Creating empty .env...")
            with open(".env", "w") as f:
                f.write("# Project Environment Variables\n")
    else:
        print("  .env already exists. Skipping.")

def main():
    # Detect platform
    current_os = platform.system()
    print(f"=== Project Setup: Detecting OS... {current_os} ===")
    
    if current_os not in ["Windows", "Darwin", "Linux"]:
        print(f"[WARNING] Unsupported OS detected: {current_os}. Proceeding anyway...")

    # Set working directory to project root
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # Step 1: Clean
    clean_project()

    # Step 2: Setup Venv
    venv_python, _ = setup_venv()

    # Step 3: Install
    install_dependencies(venv_python)

    # Step 4: Env Setup
    setup_env_file()
    
    # Ensure setup.sh is executable on Unix systems
    if current_os != "Windows" and os.path.exists("setup.sh"):
        os.chmod("setup.sh", 0o755)

    print("\n" + "="*50)
    print("✅ SETUP LOGIC COMPLETE!")
    print("="*50)
    print(f"Virtual environment location: {os.path.abspath('.venv')}")
    
    if "--no-shell" not in sys.argv:
        print("\n[IMPORTANT] To activate this environment in your current shell, run:")
        if current_os == "Windows":
            print("    .\\setup.bat")
        else:
            print("    source ./setup.sh")
    
    print("\nAlternatively, you can manually activate with:")
    if current_os == "Windows":
        print(f"    .venv\\Scripts\\activate")
    else:
        print(f"    source .venv/bin/activate")
    print("="*50)

if __name__ == "__main__":
    main()
