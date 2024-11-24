# services/process/manager.py

import os
import time
import shutil
import logging
import subprocess
import traceback
import threading
from pathlib import Path
from typing import Dict
from multiprocessing import Process, Queue, Lock
from queue import Empty
from core.config import Config
from core.exceptions import PM2CommandError, ProcessAlreadyExistsError
from services.pm2.service import PM2Service

class ProcessDeployer(Process):
    def __init__(self, config: Config, name: str, config_data: Dict, result_queue: Queue, logger: logging.Logger, lock: Lock = None):
        super().__init__()
        self.config = config
        self.name = name
        self.config_data = config_data
        self.result_queue = result_queue
        self.logger = logger
        self.pm2_service = PM2Service(config, logger)
        self.lock = lock or Lock()
        
    def run(self):
        """Execute deployment process"""
        try:
            self.logger.info(f"Starting deployment for process: {self.name}")
            self.logger.debug(f"Config data: {self.config_data}")

            # Use lock to prevent race conditions
            with self.lock:
                # Create directories
                base_path = Path("/home/pm2")
                config_dir = base_path / "pm2-configs"
                process_dir = base_path / "pm2-processes" / self.name
                logs_dir = process_dir / "logs"

                for directory in [config_dir, process_dir, logs_dir]:
                    directory.mkdir(parents=True, exist_ok=True)
                    self.logger.debug(f"Created directory: {directory}")

                # Create config file
                config_path = self.pm2_service.generate_config(
                    name=self.name,
                    repo_url=self.config_data['repository']['url'],
                    script=self.config_data.get('script', 'main.py'),
                    branch=self.config_data['repository'].get('branch', 'main'),
                    cron=self.config_data.get('cron'),
                    auto_restart=self.config_data.get('auto_restart', True),
                    env_vars=self.config_data.get('env_vars')
                )
                self.logger.debug(f"Config file created at: {config_path}")

                # Clean previous deployment
                self._run_command(f"rm -rf {process_dir}/current {process_dir}/source", "Cleanup", process_dir)

                # Clone repository
                repo_url = self.config_data['repository']['url']
                branch = self.config_data['repository'].get('branch', 'main')
                self._run_command(f"git clone -b {branch} {repo_url} {process_dir}/source", "Git Clone", process_dir)

                # Copy files
                current_dir = process_dir / "current"
                current_dir.mkdir(exist_ok=True)
                self._run_command(f"cp -r {process_dir}/source/* {current_dir}/", "Copy Files", current_dir)

                # Set up virtual environment
                self._run_command(f"python3 -m venv {process_dir}/venv", "Create venv", process_dir)

                # Install dependencies
                if (current_dir / "requirements.txt").exists():
                    self._run_command(
                        f"{process_dir}/venv/bin/pip install -r {current_dir}/requirements.txt",
                        "Install Dependencies",
                        process_dir
                    )

                # Save PM2 process list
                self._run_command("pm2 save", "PM2 Save")

                # Start the process with PM2
                self._run_command(f"pm2 start {config_path}", "Start")

                self.result_queue.put({
                    "success": True,
                    "message": f"Process {self.name} deployed successfully",
                    "config_file": str(config_path),
                })

        except Exception as e:
            self.logger.error(f"Deployment failed: {str(e)}", exc_info=True)
            self.cleanup()
            self.result_queue.put({
                "success": False,
                "message": f"Failed to deploy process {self.name}",
                "error": str(e),
                "traceback": traceback.format_exc()
            })

    def _run_command(self, cmd: str, action: str, cwd: Path = None, timeout: int = 600) -> None:
        """Run a shell command and handle output in real-time"""
        self.logger.info(f"Executing {action} command: {cmd}")
        try:
            process = subprocess.Popen(
                cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            stdout_lines = []
            stderr_lines = []

            # Function to read stdout in real-time
            def read_stdout():
                for line in iter(process.stdout.readline, ""):
                    stdout_lines.append(line.strip())
                    self.logger.debug(f"{action} STDOUT: {line.strip()}")

            # Function to read stderr in real-time
            def read_stderr():
                for line in iter(process.stderr.readline, ""):
                    stderr_lines.append(line.strip())
                    self.logger.debug(f"{action} STDERR: {line.strip()}")

            stdout_thread = threading.Thread(target=read_stdout)
            stderr_thread = threading.Thread(target=read_stderr)

            stdout_thread.start()
            stderr_thread.start()

            # Wait for the process to complete or timeout
            stdout_thread.join(timeout)
            stderr_thread.join(timeout)

            process.wait(timeout=timeout)

            if process.returncode != 0:
                raise PM2CommandError(f"{action} failed: {' '.join(stderr_lines)}")

            self.logger.info(f"{action} succeeded: {' '.join(stdout_lines)}")
        except subprocess.TimeoutExpired:
            process.kill()
            raise PM2CommandError(f"{action} command timed out")
        except Exception as e:
            raise PM2CommandError(f"{action} encountered an error: {str(e)}")
        finally:
            # Ensure streams are closed
            process.stdout.close()
            process.stderr.close()


    def cleanup(self):
        """Clean up resources on failure"""
        try:
            self.logger.info(f"Starting cleanup for failed deployment of {self.name}")
            self._run_command(f"pm2 delete {self.name}", "PM2 Delete")
            config_file = Path(f"/home/pm2/pm2-configs/{self.name}.config.js")
            process_dir = Path(f"/home/pm2/pm2-processes/{self.name}")
            if config_file.exists():
                config_file.unlink()
            if process_dir.exists():
                shutil.rmtree(process_dir)
        except Exception as e:
            self.logger.error(f"Cleanup failed: {str(e)}", exc_info=True)





