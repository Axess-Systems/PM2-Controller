# services/process/deployer.py
import os
import time
import shutil
import logging
import subprocess
import json
from pathlib import Path
from typing import Dict, Optional, Tuple
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
            # Create directories
            base_path = Path("/home/pm2")
            config_dir = base_path / "pm2-configs"
            process_dir = base_path / "pm2-processes" / self.name
            logs_dir = process_dir / "logs"

            config_dir.mkdir(parents=True, exist_ok=True)
            process_dir.mkdir(parents=True, exist_ok=True)
            logs_dir.mkdir(parents=True, exist_ok=True)

            # Create config file
            config_path = self.pm2_service.config_generator.generate_config(
                name=self.name,
                repo_url=self.config_data['repository']['url'],
                script=self.config_data.get('script', 'app.py'),
                cron=self.config_data.get('cron'),
                auto_restart=self.config_data.get('auto_restart', True),
                env_vars=self.config_data.get('env_vars')
            )

            # Run setup
            setup_result = self._run_command(
                f"pm2 deploy {config_path} production setup --force",
                "Setup"
            )
            if not setup_result['success']:
                raise PM2CommandError(f"Setup failed: {setup_result['error']}")

            # Run deploy
            deploy_result = self._run_command(
                f"pm2 deploy {config_path} production --force",
                "Deploy"
            )
            if not deploy_result['success']:
                raise PM2CommandError(f"Deploy failed: {deploy_result['error']}")

            # Verify process is running correctly
            status_result = self._check_process_status()
            if not status_result['success']:
                raise PM2CommandError(f"Process verification failed: {status_result['error']}")

            self.result_queue.put({
                "success": True,
                "message": f"Process {self.name} created and deployed successfully",
                "config_file": str(config_path)
            })

        except Exception as e:
            self.logger.error(f"Deployment failed: {str(e)}")
            error_details = self._get_error_details()
            self._cleanup()
            self.result_queue.put({
                "success": False,
                "message": f"Failed to deploy process {self.name}",
                "error": str(e),
                "error_details": error_details
            })

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
                # Check for error indicators in stdout
                if "error" in line.lower() or "failed" in line.lower():
                    error_detected = True
                    error_message = line

            # Read stderr
            stderr_line = process.stderr.readline()
            if stderr_line:
                line = stderr_line.strip()
                self.logger.error(f"[{label} Error] {line}")
                stderr_lines.append(line)
                error_detected = True
                error_message = line

            # Check if process has finished
            if process.poll() is not None:
                break

        # Get any remaining output
        remaining_stdout, remaining_stderr = process.communicate()
        if remaining_stdout:
            stdout_lines.extend(remaining_stdout.splitlines())
        if remaining_stderr:
            stderr_lines.extend(remaining_stderr.splitlines())

        success = process.returncode == 0 and not error_detected
        return {
            'success': success,
            'stdout': '\n'.join(stdout_lines),
            'stderr': '\n'.join(stderr_lines),
            'error': error_message if not success else None
        }

    def _check_process_status(self) -> Dict:
        """Check if process is running correctly"""
        try:
            # Get process info
            result = subprocess.run(
                f"pm2 show {self.name}",
                shell=True,
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                return {
                    'success': False,
                    'error': f"Process status check failed: {result.stderr}"
                }

            # Check for error indicators in process status
            status_output = result.stdout.lower()
            if "errored" in status_output or "error" in status_output:
                # Get the error details
                error_details = self._get_error_details()
                return {
                    'success': False,
                    'error': f"Process is in error state: {error_details}"
                }

            return {'success': True}

        except Exception as e:
            return {
                'success': False,
                'error': f"Failed to check process status: {str(e)}"
            }

    def _get_error_details(self) -> str:
        """Get detailed error information from PM2 logs"""
        try:
            # Get recent logs
            result = subprocess.run(
                f"pm2 logs {self.name} --lines 20 --nostream",
                shell=True,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                return f"Recent logs:\n{result.stdout}"
            return "Could not retrieve error logs"
            
        except Exception:
            return "Could not retrieve error details"

    def _cleanup(self):
        """Clean up resources on failure"""
        try:
            # Stop the process if it exists
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