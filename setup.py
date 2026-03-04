import subprocess
import os
import sys
import shutil
import platform
import urllib.request
import tempfile

IS_WINDOWS = platform.system() == "Windows"


def _resolve_system_python() -> str:
    """
    Return an absolute path to the real system (non-venv) Python interpreter.

    When the user runs `source setup.sh` or `python setup.py` from inside an
    activated venv, sys.executable points at the venv's Python.  If we then
    delete that venv and try to use the same path to re-create it, the
    executable no longer exists.  This function walks up through any
    virtualenv/venv layering to find the base interpreter.
    """
    # If we're not inside a venv, sys.executable is already the system Python.
    if not (hasattr(sys, "real_prefix") or
            (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix)):
        return sys.executable

    # sys.base_prefix is the real install root (set by venv, virtualenv, conda).
    base = getattr(sys, "base_prefix", sys.prefix)

    if IS_WINDOWS:
        candidates = [
            os.path.join(base, "python.exe"),
            os.path.join(base, "Scripts", "python.exe"),
        ]
    else:
        # Try versioned names first so we match the exact minor version.
        ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
        candidates = [
            os.path.join(base, "bin", ver),
            os.path.join(base, "bin", f"python{sys.version_info.major}"),
            os.path.join(base, "bin", "python"),
        ]

    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    # Last resort: search PATH for a python that lives outside the venv dir.
    project_venv = os.path.abspath(".venv")
    for name in (f"python{sys.version_info.major}.{sys.version_info.minor}",
                 f"python{sys.version_info.major}", "python3", "python"):
        found = shutil.which(name)
        if found and not os.path.abspath(found).startswith(project_venv):
            return found

    # Absolute fallback – may still point inside the venv but better than nothing.
    return sys.executable


# Resolve the base Python once, at import time, before any venv manipulation.
SYSTEM_PYTHON = _resolve_system_python()


def run_command(command, shell=False, check=True):
    """Run a system command. If check=True, exit on failure."""
    cmd_str = ' '.join(command) if isinstance(command, list) else command
    print(f"\n[INFO] Executing: {cmd_str}")
    try:
        # On Windows shell=True is needed for built-in commands, but for
        # absolute-path executables we keep shell=False for security.
        subprocess.check_call(command, shell=shell)
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Command failed with exit code {e.returncode}")
        if check:
            sys.exit(1)
        return False
    except FileNotFoundError:
        print(f"\n[ERROR] Could not find executable for command: {cmd_str}")
        if check:
            sys.exit(1)
        return False

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
    """Create and return absolute paths for virtual environment."""
    print("\n[INFO] Creating virtual environment...")
    print(f"[INFO] Using system Python: {SYSTEM_PYTHON}")
    run_command([SYSTEM_PYTHON, "-m", "venv", ".venv"])

    project_root = os.path.dirname(os.path.abspath(__file__))
    if IS_WINDOWS:
        venv_python = os.path.join(project_root, ".venv", "Scripts", "python.exe")
        venv_pip    = os.path.join(project_root, ".venv", "Scripts", "pip.exe")
    else:
        venv_python = os.path.join(project_root, ".venv", "bin", "python")
        venv_pip    = os.path.join(project_root, ".venv", "bin", "pip")

    return venv_python, venv_pip

def _msvc_already_installed() -> bool:
    """Return True if a usable MSVC C++ compiler is already on this machine."""
    if shutil.which("cl.exe"):
        return True
    # Check common VS install directories
    for year in ["2022", "2019", "2017"]:
        for edition in ["BuildTools", "Community", "Professional", "Enterprise"]:
            cl_dir = os.path.join(
                "C:\\", "Program Files (x86)",
                "Microsoft Visual Studio", year, edition,
                "VC", "Tools", "MSVC",
            )
            if os.path.isdir(cl_dir):
                return True
            # 64-bit Program Files
            cl_dir2 = os.path.join(
                "C:\\", "Program Files",
                "Microsoft Visual Studio", year, edition,
                "VC", "Tools", "MSVC",
            )
            if os.path.isdir(cl_dir2):
                return True
    return False


def install_cpp_build_tools():
    """
    Ensure Microsoft C++ Build Tools (MSVC) are installed on Windows.
    Required for compiling native extensions like rembg, PhotoshopAPI, psd-tools.

    Strategy:
      1. Skip if cl.exe / VS already detected.
      2. Try  winget  (available on Windows 10 1709+ and Windows 11).
      3. Fall back to downloading the official vs_buildtools bootstrapper.
    """
    if not IS_WINDOWS:
        return True

    if _msvc_already_installed():
        print("\n[INFO] Microsoft C++ compiler already present – skipping Build Tools install.")
        return True

    print("\n[INFO] Microsoft C++ Build Tools not found. Installing now...")
    print("[INFO] A UAC (administrator) prompt will appear – please accept it.")

    VC_WORKLOAD = "Microsoft.VisualStudio.Workload.VCTools"
    WINGET_FLAGS = (
        "--wait --quiet --norestart "
        f"--add ProductLang En-US --add {VC_WORKLOAD} --includeRecommended"
    )

    # ------------------------------------------------------------------
    # Attempt 1: winget (cleanest, no download overhead)
    # ------------------------------------------------------------------
    if shutil.which("winget"):
        print("[INFO] Trying winget install of Visual Studio 2022 Build Tools...")
        ok = run_command(
            [
                "winget", "install",
                "--id", "Microsoft.VisualStudio.2022.BuildTools",
                "--silent",
                "--accept-package-agreements",
                "--accept-source-agreements",
                "--override", WINGET_FLAGS,
            ],
            check=False,
        )
        if ok:
            print("[OK] C++ Build Tools installed via winget.")
            return True
        print("[WARNING] winget install returned an error – trying direct download...")

    # ------------------------------------------------------------------
    # Attempt 2: Download the VS Build Tools bootstrapper from Microsoft
    # ------------------------------------------------------------------
    bootstrapper_url = "https://aka.ms/vs/17/release/vs_buildtools.exe"
    installer_path = os.path.join(tempfile.gettempdir(), "vs_buildtools_setup.exe")

    print(f"[INFO] Downloading bootstrapper from {bootstrapper_url} ...")
    try:
        urllib.request.urlretrieve(bootstrapper_url, installer_path)
        print(f"[INFO] Saved to {installer_path}")
    except Exception as exc:
        print(f"[WARNING] Download failed: {exc}")
        print("[WARNING] Skipping automatic C++ Build Tools install.")
        print(
            "[TIP] Install manually: "
            "https://visualstudio.microsoft.com/visual-cpp-build-tools/"
        )
        return False

    print("[INFO] Running VS Build Tools installer (this may take several minutes)...")
    ok = run_command(
        [
            installer_path,
            "--wait",
            "--quiet",
            "--norestart",
            "--add", VC_WORKLOAD,
            "--includeRecommended",
        ],
        check=False,
    )

    if ok:
        print("[OK] C++ Build Tools installed successfully.")
    else:
        print(
            "[WARNING] The Build Tools installer exited with a non-zero code.\n"
            "          Optional packages (rembg, PhotoshopAPI, psd-tools) may still fail.\n"
            "          If so, run the bootstrapper manually as Administrator:\n"
            f"          {installer_path}"
        )
    return ok


# Packages that must succeed – abort setup if they fail
CRITICAL_PACKAGES = [
    "loguru",
    "playwright",
    "patchright",
    "agentql",
    "playwright-dompath",
    "requests",
    "phonenumbers",
    "pytweening",
    "unidecode",
    "python-dotenv",
    "Faker",
    "pyotp",
    "filelock",
    "psutil",
    "Pillow",
]

# Packages that are nice-to-have but may need extra build tools on Windows
OPTIONAL_PACKAGES = [
    "psd-tools",
    "PhotoshopAPI",
    "rembg[cpu]",
]


def _pkg_import_name(pkg: str) -> str:
    """Return the importable module name for a pip package name."""
    mapping = {
        "playwright-dompath": "playwright_dompath",
        "python-dotenv": "dotenv",
        "Faker": "faker",
        "Pillow": "PIL",
        "psd-tools": "psd_tools",
        "PhotoshopAPI": "photoshop",
        "rembg[cpu]": "rembg",
    }
    return mapping.get(pkg, pkg.lower().replace("-", "_").split("[")[0])


def install_dependencies(venv_python):
    """Install requirements and browser binaries with per-package error handling."""
    print("\n[INFO] Upgrading pip and setuptools...")
    run_command([venv_python, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])

    # ------------------------------------------------------------------
    # 1) Install critical packages one-by-one so a single failure never
    #    prevents the rest (e.g. loguru) from being installed.
    # ------------------------------------------------------------------
    print("\n[INFO] Installing critical packages...")
    failed_critical = []
    for pkg in CRITICAL_PACKAGES:
        ok = run_command(
            [venv_python, "-m", "pip", "install", "--upgrade", pkg],
            check=False,
        )
        if not ok:
            failed_critical.append(pkg)

    if failed_critical:
        print(f"\n[ERROR] The following CRITICAL packages failed to install: {failed_critical}")
        print("[ERROR] Please fix the errors above and re-run setup.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 2) Install optional packages – warn but don't abort on failure.
    # ------------------------------------------------------------------
    print("\n[INFO] Installing optional packages (failures are non-fatal)...")
    failed_optional = []
    for pkg in OPTIONAL_PACKAGES:
        ok = run_command(
            [venv_python, "-m", "pip", "install", "--upgrade", pkg],
            check=False,
        )
        if not ok:
            failed_optional.append(pkg)

    if failed_optional:
        print(
            f"\n[WARNING] Optional packages not installed: {failed_optional}"
        )
        if IS_WINDOWS:
            print(
                "[TIP] Make sure Visual Studio C++ Build Tools are installed, then re-run setup."
            )

    # ------------------------------------------------------------------
    # 3) Verification
    # ------------------------------------------------------------------
    print("\n[INFO] Verifying critical packages...")
    verify_pkgs = ["playwright", "agentql", "patchright", "loguru", "dotenv", "faker"]
    missing = []
    for pkg in verify_pkgs:
        result = subprocess.run(
            [venv_python, "-c", f"import {pkg}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            missing.append(pkg)

    if missing:
        print(f"[ERROR] Still missing after install: {missing}")
        sys.exit(1)
    else:
        print("  All critical packages verified.")

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

    # Step 2: Install C++ Build Tools on Windows (needed for rembg etc.)
    if current_os == "Windows":
        install_cpp_build_tools()

    # Step 3: Setup Venv
    venv_python, _ = setup_venv()

    # Step 4: Install Python dependencies
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
