# services/process/deployer.py
import os
import time
import shutil
import logging
import subprocess
import traceback
from pathlib import Path
from typing import Dict
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

    def run(self):
        """Execute deployment process"""
        try:
            self.logger.info(f"Starting deployment for process: {self.name}")
            self.logger.debug(f"Config data: {self.config_data}")
            
            # Create directories
            base_path = Path("/home/pm2")
            config_dir = base_path / "pm2-configs"
            process_dir = base_path / "pm2-processes" / self.name
            logs_dir = process_dir / "logs"

            # Create directories with logging
            for directory in [config_dir, process_dir, logs_dir]:
                directory.mkdir(parents=True, exist_ok=True)
                self.logger.debug(f"Created directory: {directory}")

            # Print current directory state
            self.logger.debug(f"Base directory contents: {list(base_path.glob('*'))}")
            self.logger.debug(f"Config directory contents: {list(config_dir.glob('*'))}")

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
            
            # Log config file contents
            self.logger.debug(f"Config file created at: {config_path}")
            with open(config_path, 'r') as f:
                self.logger.debug(f"Config file contents:\n{f.read()}")

            # Clean up existing deployment if any
            clean_cmd = f"rm -rf {process_dir}/current {process_dir}/source"
            clean_result = self.run_command(clean_cmd, "Cleanup")
            if not clean_result['success']:
                self.logger.warning(f"Cleanup warning: {clean_result['stderr']}")

            # Clone the repository first
            repo_url = self.config_data['repository']['url']
            branch = self.config_data['repository'].get('branch', 'main')
            
            clone_cmd = f"git clone -b {branch} {repo_url} {process_dir}/source"
            clone_result = self.run_command(clone_cmd, "Git Clone")
            
            if not clone_result['success']:
                raise PM2CommandError(f"Git clone failed: {clone_result['stderr']}")

            # Create the current directory and copy files
            current_dir = process_dir / "current"
            current_dir.mkdir(exist_ok=True)
            
            copy_cmd = f"cp -r {process_dir}/source/* {current_dir}/"
            copy_result = self.run_command(copy_cmd, "Copy Files")
            
            if not copy_result['success']:
                raise PM2CommandError(f"File copy failed: {copy_result['stderr']}")

            # Setup Python virtual environment
            venv_cmd = f"python3 -m venv {process_dir}/venv"
            venv_result = self.run_command(venv_cmd, "Create venv")
            
            if not venv_result['success']:
                raise PM2CommandError(f"Virtual environment creation failed: {venv_result['stderr']}")

            # Install dependencies if requirements.txt exists
            if (current_dir / "requirements.txt").exists():
                pip_cmd = f"{process_dir}/venv/bin/pip install -r {current_dir}/requirements.txt"
                pip_result = self.run_command(pip_cmd, "Install Dependencies")
                
                if not pip_result['success']:
                    raise PM2CommandError(f"Dependencies installation failed: {pip_result['stderr']}")

            # Start the process with PM2
            start_cmd = f"{self.config.PM2_BIN} start {config_path} --no-daemon"
            start_result = self.run_command(start_cmd, "Start")
            
            if not start_result['success']:
                raise PM2CommandError(f"Process start failed: {start_result['stderr']}")

            self.result_queue.put({
                "success": True,
                "message": f"Process {self.name} deployed successfully",
                "config_file": str(config_path),
                "details": {
                    "clone_output": clone_result['stdout'],
                    "deploy_output": copy_result['stdout'],
                    "start_output": start_result['stdout']
                }
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

    def run_command(self, cmd: str, label: str) -> Dict:
        """Run command with improved output capture"""
        try:
            self.logger.info(f"Running {label} command: {cmd}")
            
            # Run command and wait for completion
            process = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                env=dict(os.environ, GIT_TERMINAL_PROMPT="0")
            )
            
            stdout = process.stdout.strip()
            stderr = process.stderr.strip()

            if stdout:
                for line in stdout.splitlines():
                    self.logger.info(f"[{label}] {line.strip()}")

            if stderr:
                for line in stderr.splitlines():
                    # Don't log git clone info messages as errors
                    if "Cloning into" in line:
                        self.logger.info(f"[{label}] {line.strip()}")
                    else:
                        self.logger.error(f"[{label} Error] {line.strip()}")

            success = process.returncode == 0 and not any(
                line for line in stderr.splitlines()
                if "Cloning into" not in line and line.strip()
            )

            output = {
                'success': success,
                'stdout': stdout,
                'stderr': stderr,
                'returncode': process.returncode
            }

            self.logger.debug(f"{label} command output: {output}")
            return output

        except Exception as e:
            self.logger.error(f"{label} command failed: {str(e)}", exc_info=True)
            return {
                'success': False,
                'stdout': '',
                'stderr': str(e),
                'returncode': -1
            }
            
    def cleanup(self):
        """Clean up resources on failure"""
        try:
            self.logger.info(f"Starting cleanup for failed deployment of {self.name}")
            
            # Clean up PM2 process if it exists
            pm2_delete = self.run_command(f"{self.config.PM2_BIN} delete {self.name}", "PM2 Delete")
            self.logger.debug(f"PM2 delete result: {pm2_delete}")

            # Clean up files with logging
            config_file = Path(f"/home/pm2/pm2-configs/{self.name}.config.js")
            process_dir = Path(f"/home/pm2/pm2-processes/{self.name}")

            if config_file.exists():
                config_file.unlink()
                self.logger.debug(f"Removed config file: {config_file}")

            if process_dir.exists():
                shutil.rmtree(process_dir)
                self.logger.debug(f"Removed process directory: {process_dir}")

        except Exception as e:
            self.logger.error(f"Cleanup failed: {str(e)}", exc_info=True)