# services/process/deployer.py
import os
import time
import shutil
import logging
import subprocess
import threading
from pathlib import Path
from typing import Dict
from multiprocessing import Process, Queue
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
                script=self.config_data.get('script', 'main.py'),
                cron=self.config_data.get('cron'),
                auto_restart=self.config_data.get('auto_restart', True),
                env_vars=self.config_data.get('env_vars')
            )

            # Run setup and deploy
            setup_result = self.run_command(
                f"pm2 deploy {config_path} production setup --force",
                "Setup"
            )
            
            if not setup_result.get('success'):
                raise PM2CommandError(f"Setup failed: {setup_result.get('error')}")

            deploy_result = self.run_command(
                f"pm2 deploy {config_path} production --force",
                "Deploy"
            )
            
            if not deploy_result.get('success'):
                raise PM2CommandError(f"Deploy failed: {deploy_result.get('error')}")

            self.result_queue.put({
                "success": True,
                "message": f"Process {self.name} created and deployed successfully",
                "config_file": str(config_path)
            })

        except Exception as e:
            self.logger.error(f"Deployment failed: {str(e)}")
            self.cleanup()
            self.result_queue.put({
                "success": False,
                "message": f"Failed to deploy process {self.name}",
                "error": str(e)
            })

    def run_command(self, cmd: str, label: str) -> Dict:
        """Run command with non-blocking output handling"""
        try:
            self.logger.info(f"Running command: {cmd}")
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=dict(os.environ, PM2_SILENT='true')
            )

            stdout_data = []
            stderr_data = []
            error_detected = False
            error_message = None

            # Set pipes to non-blocking mode
            for pipe in [process.stdout, process.stderr]:
                flags = fcntl.fcntl(pipe.fileno(), fcntl.F_GETFL)
                fcntl.fcntl(pipe.fileno(), fcntl.F_SETFL, flags | os.O_NONBLOCK)

            while process.poll() is None:
                # Read from stdout
                try:
                    stdout = process.stdout.read().decode()
                    if stdout:
                        lines = stdout.splitlines()
                        for line in lines:
                            if line.strip():
                                self.logger.info(f"[{label}] {line.strip()}")
                                stdout_data.append(line.strip())
                except (IOError, BlockingIOError):
                    pass

                # Read from stderr
                try:
                    stderr = process.stderr.read().decode()
                    if stderr:
                        lines = stderr.splitlines()
                        for line in lines:
                            if line.strip() and "Cloning into" not in line:
                                self.logger.error(f"[{label} Error] {line.strip()}")
                                stderr_data.append(line.strip())
                                error_detected = True
                                error_message = line.strip()
                except (IOError, BlockingIOError):
                    pass

                # Short sleep to prevent CPU thrashing
                time.sleep(0.1)

            # Get any remaining output
            stdout, stderr = process.communicate()
            if stdout:
                lines = stdout.decode().splitlines()
                for line in lines:
                    if line.strip():
                        self.logger.info(f"[{label}] {line.strip()}")
                        stdout_data.append(line.strip())
            if stderr:
                lines = stderr.decode().splitlines()
                for line in lines:
                    if line.strip() and "Cloning into" not in line:
                        self.logger.error(f"[{label} Error] {line.strip()}")
                        stderr_data.append(line.strip())
                        error_detected = True
                        error_message = line.strip()

            success = process.returncode == 0 and not error_detected
            return {
                'success': success,
                'error': error_message if not success else None
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }


    def cleanup(self):
        """Clean up resources on failure"""
        try:
            # Stop and delete PM2 process
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