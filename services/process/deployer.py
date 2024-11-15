# services/process/deployer.py
import os
import time
import errno
from select import select
import fcntl
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
            setup_result = self.run_command(
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
            deploy_result = self.run_command(
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

            # Verify process is running
            status_result = self.check_process_status()
            if not status_result.get('success'):
                error_message = (
                    f"Process verification failed:\n"
                    f"Error: {status_result.get('error', 'Unknown error')}\n"
                    f"Deploy STDOUT: {deploy_result.get('stdout', '')}\n"
                    f"Deploy STDERR: {deploy_result.get('stderr', '')}"
                )
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
            error_details = self.get_error_details()
            self.cleanup()
            self.result_queue.put({
                "success": False,
                "message": f"Failed to deploy process {self.name}",
                "error": str(e),
                "error_details": error_details
            })

    def run_command(self, cmd: str, label: str, timeout: int = 300) -> Dict:
        """Run command and capture output with error handling and timeout"""
        from select import select
        import fcntl
        import os

        process = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        # Set non-blocking mode for pipes
        for pipe in [process.stdout, process.stderr]:
            flags = fcntl.fcntl(pipe.fileno(), fcntl.F_GETFL)
            fcntl.fcntl(pipe.fileno(), fcntl.F_SETFL, flags | os.O_NONBLOCK)

        stdout_lines = []
        stderr_lines = []
        error_detected = False
        error_message = None
        
        start_time = time.time()

        while True:
            # Check timeout
            if time.time() - start_time > timeout:
                process.terminate()
                return {
                    'success': False,
                    'stdout': '\n'.join(stdout_lines),
                    'stderr': '\n'.join(stderr_lines),
                    'error': f'Command timed out after {timeout} seconds',
                    'returncode': -1
                }

            # Wait for output with timeout
            reads = [process.stdout.fileno(), process.stderr.fileno()]
            ready_reads, _, _ = select(reads, [], [], 1.0)

            try:
                # Handle stdout
                if process.stdout.fileno() in ready_reads:
                    line = process.stdout.readline()
                    if line:
                        line = line.strip()
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
                        ]) and "Cloning into" not in line:
                            error_detected = True
                            error_message = line

                # Handle stderr
                if process.stderr.fileno() in ready_reads:
                    line = process.stderr.readline()
                    if line:
                        line = line.strip()
                        if "Cloning into" not in line:
                            self.logger.error(f"[{label} Error] {line}")
                            stderr_lines.append(line)
                            error_detected = True
                            error_message = line

            except (IOError, OSError) as e:
                # Handle pipe errors
                if e.errno != errno.EAGAIN:
                    self.logger.error(f"Pipe error: {str(e)}")
                    break

            # Check if process has finished
            if process.poll() is not None:
                # Read any remaining output
                try:
                    remaining_stdout = process.stdout.read()
                    if remaining_stdout:
                        stdout_lines.extend(remaining_stdout.splitlines())
                    remaining_stderr = process.stderr.read()
                    if remaining_stderr:
                        stderr_lines.extend(remaining_stderr.splitlines())
                except:
                    pass
                break

            # Small sleep to prevent CPU thrashing
            time.sleep(0.1)

        return {
            'success': process.returncode == 0 and not error_detected,
            'stdout': '\n'.join(stdout_lines),
            'stderr': '\n'.join(stderr_lines),
            'error': error_message if error_detected else None,
            'returncode': process.returncode
        }
    
    def check_process_status(self) -> Dict:
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

    def get_error_details(self) -> str:
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

    def cleanup(self):
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