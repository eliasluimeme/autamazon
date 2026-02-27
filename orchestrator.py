"""
Amazon Automation Parallel Orchestrator
Manages multiple concurrent AdsPower/Playwright sessions.
"""
import asyncio
import argparse
import os
import sys
from loguru import logger

from utils.cleanup import kill_zombie_processes

# Configure logging to console
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>")

import signal

# Track active processes for cleanup
active_processes = set()

async def run_profile_task(profile_id, semaphore, product=None):
    """Executes run.py for a specific profile within concurrency limits, with retries."""
    max_retries = 3
    for attempt in range(max_retries):
        async with semaphore:
            logger.info(f"🚀 [Attempt {attempt+1}/{max_retries}] Starting task for Profile: {profile_id}")
            
            # Define log file for this specific profile
            log_dir = "logs"
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, f"{profile_id}.log")
            
            # Build command
            cmd = [sys.executable, "run.py", profile_id]
            if product:
                cmd.extend(["--product", product])
                
            process = None
            try:
                # Run as subprocess
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                active_processes.add(process)
                
                # Helper to pipe output to file
                async def log_stream(stream, prefix):
                    with open(log_file, "a") as f:
                        f.write(f"\n--- ATTEMPT {attempt+1} START ---\n")
                        while True:
                            try:
                                line = await stream.readline()
                                if not line:
                                    break
                                decoded_line = line.decode().strip()
                                f.write(f"[{prefix}] {decoded_line}\n")
                                f.flush()
                            except asyncio.CancelledError:
                                break
                
                # Wait for completion and log streams
                await asyncio.gather(
                    log_stream(process.stdout, "STDOUT"),
                    log_stream(process.stderr, "STDERR"),
                    process.wait()
                )
                
                if process.returncode == 0:
                    logger.success(f"✅ Profile {profile_id} completed successfully.")
                    return # Exit retry loop on success
                else:
                    logger.warning(f"⚠️ Profile {profile_id} failed with exit code {process.returncode} on attempt {attempt+1}.")
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 5
                        logger.info(f"🕒 Waiting {wait_time}s before retry...")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"❌ Profile {profile_id} failed after {max_retries} attempts.")
                    
            except asyncio.CancelledError:
                if process:
                    try:
                        process.terminate()
                        await process.wait()
                    except: pass
                raise
            except Exception as e:
                logger.exception(f"Exception while running profile {profile_id}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)
                else:
                    break
            finally:
                if process in active_processes:
                    active_processes.remove(process)

async def shutdown(sig, loop):
    """Cleanup tasks on termination signal."""
    logger.info(f"Received exit signal {sig.name}...")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    
    logger.info(f"Terminating {len(active_processes)} active subprocesses...")
    for p in active_processes:
        try:
            p.terminate()
        except: pass
        
    logger.info(f"Cancelling {len(tasks)} tasks...")
    [task.cancel() for task in tasks]
    
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()

async def main():
    parser = argparse.ArgumentParser(description="Amazon Parallel Orchestrator")
    parser.add_argument("--profiles", nargs="+", required=True, help="List of Profile IDs to run")
    parser.add_argument("--concurrency", type=int, default=3, help="Max concurrent profiles (default: 3)")
    parser.add_argument("--product", type=str, help="Optional product to search")
    
    args = parser.parse_args()
    
    # 1. Initial cleanup
    kill_zombie_processes()
    
    if not args.profiles:
        logger.error("No profiles provided.")
        return

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s, loop)))

    logger.info(f"🌟 Starting Orchestrator with {len(args.profiles)} profiles (Max Concurrency: {args.concurrency})")
    
    semaphore = asyncio.Semaphore(args.concurrency)
    tasks = [run_profile_task(pid, semaphore, args.product) for pid in args.profiles]
    
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.warning("Main task cancelled.")
    finally:
        logger.info("🏁 All tasks finished.")
        # 2. Final cleanup
        kill_zombie_processes()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
