# services/process/deployer.py
import os
import time
import shutil
import logging
import subprocess
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
            
            # Create directories
            base_path = Path("/home/pm2")
            config_dir = base_path / "pm2-configs"
            process_dir = base_path / "pm2-processes" / self.name
            logs_dir = process_dir / "logs"

            # Create directories with logging
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
            
            self.logger.info(f"Created config file at: {config_path}")

            # Clean up existing deployment if any
            clean_cmd = f"rm -rf {process_dir}/current {process_dir}/source"
            clean_result = subprocess.run(clean_cmd, shell=True, capture_output=True, text=True)
            if clean_result.returncode != 0:
                self.logger.warning(f"Cleanup warning: {clean_result.stderr}")

            # Setup the deployment
            setup_cmd = f"{self.config.PM2_BIN} deploy {config_path} production setup 2>&1"
            setup_process = subprocess.run(
                setup_cmd,
                shell=True,
                capture_output=True,
                text=True
            )
            
            setup_output = setup_process.stdout + setup_process.stderr
            self.logger.info(f"Setup output: {setup_output}")
            
            if setup_process.returncode != 0:
                raise PM2CommandError(f"Setup failed: {setup_output}")

            # Clone the repository
            repo_url = self.config_data['repository']['url']
            branch = self.config_data['repository'].get('branch', 'main')
            
            clone_cmd = f"git clone -b {branch} {repo_url} {process_dir}/source"
            clone_result = subprocess.run(clone_cmd, shell=True, capture_output=True, text=True)
            
            if clone_result.returncode != 0:
                raise PM2CommandError(f"Git clone failed: {clone_result.stderr}")

            # Deploy the application
            deploy_cmd = f"{self.config.PM2_BIN} deploy {config_path} production 2>&1"
            deploy_process = subprocess.run(
                deploy_cmd,
                shell=True,
                capture_output=True,
                text=True
            )
            
            deploy_output = deploy_process.stdout + deploy_process.stderr
            self.logger.info(f"Deploy output: {deploy_output}")
            
            if deploy_process.returncode != 0:
                raise PM2CommandError(f"Deploy failed: {deploy_output}")

            # Start the process
            start_cmd = f"{self.config.PM2_BIN} start {config_path} 2>&1"
            start_process = subprocess.run(
                start_cmd,
                shell=True,
                capture_output=True,
                text=True
            )
            
            start_output = start_process.stdout + start_process.stderr
            self.logger.info(f"Start output: {start_output}")
            
            if start_process.returncode != 0:
                raise PM2CommandError(f"Start failed: {start_output}")

            self.result_queue.put({
                "success": True,
                "message": f"Process {self.name} deployed successfully",
                "config_file": str(config_path),
                "details": {
                    "setup_output": setup_output,
                    "deploy_output": deploy_output,
                    "start_output": start_output
                }
            })

        except Exception as e:
            self.logger.error(f"Deployment failed: {str(e)}", exc_info=True)
            self.cleanup()
            self.result_queue.put({
                "success": False,
                "message": f"Failed to deploy process {self.name}",
                "error": str(e)
            })       
            
    def run_command(self, cmd: str, label: str) -> Dict:
        """Run command with improved output capture"""
        try:
            self.logger.info(f"Running {label} command: {cmd}")
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=dict(os.environ, PM2_SILENT='true')
            )

            stdout_lines = []
            stderr_lines = []

            while True:
                # Read stdout
                stdout_line = process.stdout.readline()
                if stdout_line:
                    line = stdout_line.strip()
                    if line:
                        stdout_lines.append(line)
                        self.logger.info(f"[{label}] {line}")

                # Read stderr
                stderr_line = process.stderr.readline()
                if stderr_line:
                    line = stderr_line.strip()
                    if line:
                        stderr_lines.append(line)
                        self.logger.error(f"[{label} Error] {line}")

                # Check if process has finished
                if process.poll() is not None:
                    break

            output = {
                'success': process.returncode == 0 and not stderr_lines,
                'stdout': '\n'.join(stdout_lines),
                'stderr': '\n'.join(stderr_lines),
                'error': '\n'.join(stderr_lines) if stderr_lines else None
            }

            self.logger.debug(f"{label} command output: {output}")
            return output

        except Exception as e:
            self.logger.error(f"{label} command failed: {str(e)}", exc_info=True)
            return {
                'success': False,
                'stdout': '',
                'stderr': str(e),
                'error': str(e)
            }
            
    def cleanup(self):
        """Clean up resources on failure"""
        try:
            name = self.name
            self.logger.info(f"Starting cleanup for failed deployment of {name}")
            
            # Clean up PM2 process if it exists
            subprocess.run(
                f"{self.config.PM2_BIN} delete {name}",
                shell=True,
                capture_output=True,
                text=True
            )

            # Clean up files
            config_file = Path(f"/home/pm2/pm2-configs/{name}.config.js")
            process_dir = Path(f"/home/pm2/pm2-processes/{name}")

            if config_file.exists():
                config_file.unlink()
                self.logger.info(f"Removed config file: {config_file}")

            if process_dir.exists():
                import shutil
                shutil.rmtree(process_dir)
                self.logger.info(f"Removed process directory: {process_dir}")

        except Exception as e:
            self.logger.error(f"Cleanup failed: {str(e)}", exc_info=True)
   
   