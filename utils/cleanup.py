"""
Enhanced Resource Cleanup Utility

Improvements over V1:
    - Graceful shutdown (SIGTERM first, SIGKILL after timeout)
    - Tracks resources that were opened during this session
    - Avoids killing personal browser instances
    - Process tree traversal for child process cleanup
    - Works with or without psutil (graceful degradation)
"""

import os
import time
import signal
import subprocess
from typing import Set, Optional
from loguru import logger

# psutil is optional — degrade gracefully if not available
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.debug("psutil not available — using subprocess fallback for cleanup")


# Track PIDs of processes WE started (not external)
_tracked_pids: Set[int] = set()


def track_pid(pid: int):
    """Register a PID as started by this automation session."""
    _tracked_pids.add(pid)


def untrack_pid(pid: int):
    """Remove a PID from tracking."""
    _tracked_pids.discard(pid)


def graceful_kill(pid: int, timeout: float = 5.0) -> bool:
    """
    Kill a process gracefully: SIGTERM first, SIGKILL after timeout.
    
    Args:
        pid: Process ID to kill
        timeout: Seconds to wait for graceful exit before SIGKILL
        
    Returns:
        True if process was killed
    """
    if PSUTIL_AVAILABLE:
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=timeout)
                return True
            except psutil.TimeoutExpired:
                pass
            proc.kill()
            proc.wait(timeout=2)
            return True
        except psutil.NoSuchProcess:
            return True
        except psutil.AccessDenied:
            logger.warning(f"Access denied killing PID {pid}")
            return False
        except Exception as e:
            logger.warning(f"Failed to kill PID {pid}: {e}")
            return False
    else:
        # Fallback: os.kill
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(min(timeout, 3))
            # Check if still alive
            try:
                os.kill(pid, 0)  # Signal 0 just checks if process exists
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # Already gone
            return True
        except ProcessLookupError:
            return True
        except PermissionError:
            logger.warning(f"Access denied killing PID {pid}")
            return False
        except Exception as e:
            logger.warning(f"Failed to kill PID {pid}: {e}")
            return False


def kill_process_tree(pid: int, timeout: float = 5.0) -> int:
    """
    Kill a process and all its children.
    
    Args:
        pid: Root process ID
        timeout: Seconds to wait for graceful exit
        
    Returns:
        Number of processes killed
    """
    count = 0
    
    if PSUTIL_AVAILABLE:
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            
            for child in reversed(children):
                try:
                    child.terminate()
                    count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            _, alive = psutil.wait_procs(children, timeout=timeout)
            for p in alive:
                try:
                    p.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            if graceful_kill(pid, timeout):
                count += 1
                
        except psutil.NoSuchProcess:
            pass
        except Exception as e:
            logger.warning(f"Process tree cleanup error for PID {pid}: {e}")
    else:
        # Fallback: just kill the single process
        if graceful_kill(pid, timeout):
            count = 1
    
    return count


def _get_process_list_fallback():
    """Get process list using `ps` command when psutil is unavailable."""
    try:
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=10
        )
        processes = []
        for line in result.stdout.strip().split("\n")[1:]:
            parts = line.split(None, 10)
            if len(parts) >= 11:
                processes.append({
                    "pid": int(parts[1]),
                    "name": parts[10].split("/")[-1].split(" ")[0],
                    "cmdline": parts[10],
                })
        return processes
    except Exception as e:
        logger.warning(f"Could not list processes: {e}")
        return []


def kill_zombie_processes():
    """
    Kill automation-specific zombie processes.
    
    Enhanced version that:
    - Only kills processes with automation markers
    - Uses graceful shutdown (SIGTERM → SIGKILL)
    - Avoids false positives with personal browser instances
    - Works with or without psutil
    """
    logger.info("🧹 Scanning for automation-specific zombie processes...")
    
    current_pid = os.getpid()
    count = 0
    
    if PSUTIL_AVAILABLE:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'ppid']):
            try:
                if proc.info['pid'] == current_pid:
                    continue
                    
                proc_name = (proc.info['name'] or '').lower()
                cmdline_list = proc.info['cmdline'] or []
                cmdline = " ".join(cmdline_list).lower()
                
                should_kill = False
                kill_reason = ""
                
                # 1. High-signal automation patterns
                for pattern in ["patchright", "playwright"]:
                    if pattern in proc_name or pattern in cmdline:
                        should_kill = True
                        kill_reason = f"Automation pattern: {pattern}"
                        break
                
                # 2. Tracked PIDs
                if not should_kill and proc.info['pid'] in _tracked_pids:
                    should_kill = True
                    kill_reason = "Tracked automation PID"
                
                # 3. Browser processes with automation markers
                if not should_kill:
                    is_browser = any(
                        bp in proc_name or bp in cmdline 
                        for bp in ["chrome", "chromium"]
                    )
                    if is_browser:
                        automation_markers = [
                            "adspower",
                            "--enable-automation",
                            "headless",
                            "--remote-debugging-port",
                            "sun-flower",
                        ]
                        if any(marker in cmdline for marker in automation_markers):
                            should_kill = True
                            kill_reason = "Browser with automation markers"
                
                if should_kill:
                    logger.debug(
                        f"Killing: {proc.info['name']} (PID: {proc.info['pid']}) "
                        f"— {kill_reason}"
                    )
                    killed = kill_process_tree(proc.info['pid'], timeout=3)
                    count += killed
                    
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    else:
        # Fallback: use ps command
        for proc in _get_process_list_fallback():
            try:
                if proc['pid'] == current_pid:
                    continue
                
                cmdline = proc['cmdline'].lower()
                proc_name = proc['name'].lower()
                
                should_kill = False
                
                for pattern in ["patchright", "playwright"]:
                    if pattern in proc_name or pattern in cmdline:
                        should_kill = True
                        break
                
                if not should_kill and proc['pid'] in _tracked_pids:
                    should_kill = True
                
                if not should_kill:
                    is_browser = any(bp in proc_name for bp in ["chrome", "chromium"])
                    if is_browser:
                        markers = ["adspower", "--enable-automation", "headless", "--remote-debugging-port"]
                        if any(m in cmdline for m in markers):
                            should_kill = True
                
                if should_kill:
                    logger.debug(f"Killing: {proc['name']} (PID: {proc['pid']})")
                    if graceful_kill(proc['pid'], timeout=3):
                        count += 1
                        
            except Exception:
                continue
    
    if count > 0:
        logger.success(f"✅ Cleaned up {count} zombie processes.")
    else:
        logger.info("✨ No zombie processes found.")
    
    return count


def cleanup_adspower_sessions(
    api_url: str = "http://local.adspower.net:50325",
    profile_ids: Optional[list] = None
):
    """
    Cleanup orphaned AdsPower browser sessions via API.
    
    Args:
        api_url: AdsPower API URL
        profile_ids: Specific profiles to stop (None = skip)
    """
    logger.info("🧹 Checking for orphaned AdsPower sessions...")
    
    try:
        import requests
    except ImportError:
        logger.warning("requests not available — skipping AdsPower cleanup")
        return
    
    if profile_ids:
        for pid in profile_ids:
            try:
                url = f"{api_url}/api/v1/browser/stop?user_id={pid}"
                resp = requests.get(url, timeout=5)
                if resp.ok:
                    data = resp.json()
                    if data.get("code") == 0:
                        logger.info(f"Stopped orphaned session: {pid}")
            except Exception:
                pass


def get_resource_usage() -> dict:
    """
    Get current resource usage metrics for monitoring.
    
    Returns:
        Dict with CPU, memory, and process counts
    """
    if not PSUTIL_AVAILABLE:
        return {"error": "psutil not available"}
    
    try:
        process = psutil.Process(os.getpid())
        
        automation_procs = 0
        browser_procs = 0
        for proc in psutil.process_iter(['name', 'cmdline']):
            try:
                cmdline = " ".join(proc.info['cmdline'] or []).lower()
                name = (proc.info['name'] or '').lower()
                
                if any(p in name or p in cmdline for p in ["patchright", "playwright"]):
                    automation_procs += 1
                if any(p in name for p in ["chrome", "chromium"]):
                    browser_procs += 1
            except:
                pass
        
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent,
            "memory_available_mb": psutil.virtual_memory().available / (1024 * 1024),
            "process_memory_mb": process.memory_info().rss / (1024 * 1024),
            "automation_processes": automation_procs,
            "browser_processes": browser_procs,
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    kill_zombie_processes()
    print("\nResource Usage:")
    for k, v in get_resource_usage().items():
        if isinstance(v, float):
            print(f"  {k}: {v:.1f}")
        else:
            print(f"  {k}: {v}")
