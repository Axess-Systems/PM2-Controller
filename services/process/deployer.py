# services/process/deployer.py
import os
import time
import shutil
import logging
import subprocess
import json
from pathlib import Path
from typing import Dict, Optional
from multiprocessing import Process, Queue
from queue import Empty
from core.config import Config
from core.exceptions import PM2CommandError
from services.pm2.service import PM2Service

class ProcessDeployer(Process):
    def __init__(self, config: Config, name: str, config_data: Dict, result_queue: Queue, logger: logging.Logger):
        super().__init__()
        self.config = config
        self.name = name
        self.config_data = config_data
        self.result_queue = result_queue
        self.logger = logger
        self.pm2_service = PM2Service(config, logger)

    def _run_command(self, cmd: str, label: str) -> Dict:
        """Run command and capture output with error handling"""
        process = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        stdout_lines = []
        stderr_lines = []
        error_detected = False
        error_message = None

        while True:
            # Read stdout
            stdout_line = process.stdout.readline()
            if stdout_line:
                line = stdout_line.strip()
                self.logger.info(f"[{label}] {line}")
                stdout_lines.append(line)
                # Check for specific error messages
                if any(x in line.lower() for x in [
                    "error",
                    "failed",
                    "not found",
                    "cannot access",
                    "permission denied",
                    "fatal"
                ]):
                    error_detected = True
                    error_message = line

            # Read stderr
            stderr_line = process.stderr.readline()
            if stderr_line:
                line = stderr_line.strip()
                # Don't treat git clone messages as errors
                if "Cloning into" not in line:
                    self.logger.error(f"[{label} Error] {line}")
                    stderr_lines.append(line)
                    error_detected = True
                    error_message = line

            # Check if process has finished
            if process.poll() is not None:
                break

        # Get remaining output
        remaining_stdout, remaining_stderr = process.communicate()
        if remaining_stdout:
            stdout_lines.extend(remaining_stdout.splitlines())
        if remaining_stderr:
            stderr_lines.extend(remaining_stderr.splitlines())

        return {
            'success': process.returncode == 0 and not error_detected,
            'stdout': '\n'.join(stdout_lines),
            'stderr': '\n'.join(stderr_lines),
            'error': error_message if error_detected else None,
            'returncode': process.returncode
        }

    def _check_process_status(self) -> Dict:
        """Check if process is running correctly"""
        try:
            result = subprocess.run(
                f"pm2 show {self.name}",
                shell=True,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                return {
                    'success': False,
                    'error': f"Failed to get process status: {result.stderr}"
                }

            # Check process status
            output = result.stdout.lower()
            if "errored" in output or "error" in output:
                return {
                    'success': False,
                    'error': f"Process is in error state: {result.stdout}"
                }

            return {'success': True}

        except Exception as e:
            return {
                'success': False,
                'error': f"Error checking process status: {str(e)}"
            }

    def _get_error_details(self) -> str:
        """Get error details from logs"""
        try:
            result = subprocess.run(
                f"pm2 logs {self.name} --lines 20 --nostream",
                shell=True,
                capture_output=True,
                text=True
            )
            return result.stdout if result.returncode == 0 else "Could not retrieve logs"
        except Exception as e:
            return f"Error getting logs: {str(e)}"

    def _cleanup(self):
        """Clean up resources on failure"""
        try:
            # Try to stop and delete the PM2 process
            subprocess.run(f"pm2 stop {self.name}", shell=True, check=False)
            subprocess.run(f"pm2 delete {self.name}", shell=True, check=False)

            # Clean up files
            for path in [
                Path(f"/home/pm2/pm2-configs/{self.name}.config.js"),
                Path(f"/home/pm2/pm2-processes/{self.name}")
            ]:
                if path.exists():
                    if path.is_file():
                        path.unlink()
                    else:
                        shutil.rmtree(path)
        except Exception as e:
            self.logger.error(f"Cleanup failed: {str(e)}")