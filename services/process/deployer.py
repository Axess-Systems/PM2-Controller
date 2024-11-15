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
            self.logger.info(f"Starting setup for {self.name}")
            setup_result = self._run_command(
                f"pm2 deploy {config_path} production setup --force",
                "Setup"
            )
            if not setup_result['success']:
                raise PM2CommandError(
                    f"Setup failed (code: {setup_result['returncode']}): {setup_result['error']}\n"
                    f"STDOUT: {setup_result['stdout']}\n"
                    f"STDERR: {setup_result['stderr']}"
                )

            # Verify setup
            if not Path(f"{process_dir}/source").exists():
                raise PM2CommandError(
                    f"Setup failed: Source directory not created\n"
                    f"STDOUT: {setup_result['stdout']}\n"
                    f"STDERR: {setup_result['stderr']}"
                )

            # Run deploy
            self.logger.info(f"Starting deployment for {self.name}")
            deploy_result = self._run_command(
                f"pm2 deploy {config_path} production --force",
                "Deploy"
            )
            if not deploy_result['success']:
                raise PM2CommandError(
                    f"Deploy failed (code: {deploy_result['returncode']}): {deploy_result['error']}\n"
                    f"STDOUT: {deploy_result['stdout']}\n"
                    f"STDERR: {deploy_result['stderr']}"
                )

            # Verify deployment
            status_result = self._check_process_status()
            if not status_result['success']:
                raise PM2CommandError(
                    f"Process verification failed: {status_result['error']}\n"
                    f"Deploy STDOUT: {deploy_result['stdout']}\n"
                    f"Deploy STDERR: {deploy_result['stderr']}"
                )

            # Check if process is actually running
            jlist_result = subprocess.run(
                "pm2 jlist",
                shell=True,
                capture_output=True,
                text=True
            )
            if jlist_result.returncode == 0:
                try:
                    processes = json.loads(jlist_result.stdout)
                    process = next((p for p in processes if p['name'] == self.name), None)
                    if not process:
                        raise PM2CommandError(
                            f"Process {self.name} not found in PM2 process list after deployment\n"
                            f"Deploy STDOUT: {deploy_result['stdout']}\n"
                            f"Deploy STDERR: {deploy_result['stderr']}"
                        )
                    if process.get('pm2_env', {}).get('status') != 'online':
                        raise PM2CommandError(
                            f"Process {self.name} is not running (status: {process.get('pm2_env', {}).get('status')})\n"
                            f"Deploy STDOUT: {deploy_result['stdout']}\n"
                            f"Deploy STDERR: {deploy_result['stderr']}"
                        )
                except json.JSONDecodeError:
                    raise PM2CommandError(
                        f"Failed to parse PM2 process list\n"
                        f"PM2 output: {jlist_result.stdout}"
                    )

            self.result_queue.put({
                "success": True,
                "message": f"Process {self.name} created and deployed successfully",
                "config_file": str(config_path),
                "setup_output": setup_result['stdout'],
                "deploy_output": deploy_result['stdout']
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
            self.logger.info(f"Starting setup for {self.name}")
            setup_result = self._run_command(
                f"pm2 deploy {config_path} production setup --force",
                "Setup"
            )
            
            if not setup_result.get('success'):
                error_message = (
                    f"Setup failed:\n"
                    f"Error: {setup_result.get('error', 'Unknown error')}\n"
                    f"Return Code: {setup_result.get('returncode', 'N/A')}\n"
                    f"STDOUT: {setup_result.get('stdout', '')}\n"
                    f"STDERR: {setup_result.get('stderr', '')}"
                )
                raise PM2CommandError(error_message)

            # Verify setup
            if not Path(f"{process_dir}/source").exists():
                error_message = (
                    f"Setup completed but source directory not created:\n"
                    f"STDOUT: {setup_result.get('stdout', '')}\n"
                    f"STDERR: {setup_result.get('stderr', '')}"
                )
                raise PM2CommandError(error_message)

            # Run deploy
            self.logger.info(f"Starting deployment for {self.name}")
            deploy_result = self._run_command(
                f"pm2 deploy {config_path} production --force",
                "Deploy"
            )
            
            if not deploy_result.get('success'):
                error_message = (
                    f"Deploy failed:\n"
                    f"Error: {deploy_result.get('error', 'Unknown error')}\n"
                    f"Return Code: {deploy_result.get('returncode', 'N/A')}\n"
                    f"STDOUT: {deploy_result.get('stdout', '')}\n"
                    f"STDERR: {deploy_result.get('stderr', '')}"
                )
                raise PM2CommandError(error_message)

            # Verify deployment
            status_result = self._check_process_status()
            if not status_result.get('success'):
                error_message = (
                    f"Process verification failed:\n"
                    f"Status Error: {status_result.get('error', 'Unknown error')}\n"
                    f"Deploy STDOUT: {deploy_result.get('stdout', '')}\n"
                    f"Deploy STDERR: {deploy_result.get('stderr', '')}"
                )
                raise PM2CommandError(error_message)

            # Check if process is actually running
            jlist_result = subprocess.run(
                "pm2 jlist",
                shell=True,
                capture_output=True,
                text=True
            )
            
            if jlist_result.returncode == 0:
                try:
                    processes = json.loads(jlist_result.stdout)
                    process = next((p for p in processes if p['name'] == self.name), None)
                    
                    if not process:
                        error_message = (
                            f"Process {self.name} not found in PM2 process list after deployment:\n"
                            f"Deploy STDOUT: {deploy_result.get('stdout', '')}\n"
                            f"Deploy STDERR: {deploy_result.get('stderr', '')}"
                        )
                        raise PM2CommandError(error_message)
                        
                    if process.get('pm2_env', {}).get('status') != 'online':
                        error_message = (
                            f"Process {self.name} is not running:\n"
                            f"Status: {process.get('pm2_env', {}).get('status', 'unknown')}\n"
                            f"Deploy STDOUT: {deploy_result.get('stdout', '')}\n"
                            f"Deploy STDERR: {deploy_result.get('stderr', '')}"
                        )
                        raise PM2CommandError(error_message)
                        
                except json.JSONDecodeError:
                    error_message = f"Failed to parse PM2 process list:\nPM2 output: {jlist_result.stdout}"
                    raise PM2CommandError(error_message)

            self.result_queue.put({
                "success": True,
                "message": f"Process {self.name} created and deployed successfully",
                "config_file": str(config_path),
                "setup_output": setup_result.get('stdout', ''),
                "deploy_output": deploy_result.get('stdout', '')
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