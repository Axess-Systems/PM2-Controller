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
            source_dir = process_dir / "source"
            if not source_dir.exists():
                error_message = (
                    f"Setup completed but source directory not created at {source_dir}:\n"
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

            # Verify deployment
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
        """Run command and capture output"""
        # Shared state for output tracking
        class OutputState:
            def __init__(self):
                self.error_detected = False
                self.error_message = None
                self.stdout_lines = []
                self.stderr_lines = []

        state = OutputState()
        
        def read_output(pipe, queue, is_stderr):
            """Read output from pipe to queue"""
            try:
                for line in iter(pipe.readline, ''):
                    stripped = line.strip()
                    if stripped:
                        if is_stderr:
                            # Don't treat git clone messages as errors
                            if "Cloning into" not in stripped:
                                self.logger.error(f"[{label} Error] {stripped}")
                                queue.put(stripped)
                                state.error_detected = True
                                state.error_message = stripped
                        else:
                            self.logger.info(f"[{label}] {stripped}")
                            queue.put(stripped)
                            # Check for error indicators in output
                            if any(x in stripped.lower() for x in [
                                "error",
                                "failed",
                                "not found",
                                "cannot access",
                                "permission denied",
                                "fatal"
                            ]) and "Cloning into" not in stripped:
                                state.error_detected = True
                                state.error_message = stripped
            except Exception as e:
                self.logger.error(f"Error reading output: {str(e)}")
            finally:
                pipe.close()

        try:
            # Start the process
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )

            # Set up output collection
            stdout_queue = Queue()
            stderr_queue = Queue()

            # Start output reader threads
            stdout_thread = threading.Thread(
                target=read_output,
                args=(process.stdout, stdout_queue, False)
            )
            stderr_thread = threading.Thread(
                target=read_output,
                args=(process.stderr, stderr_queue, True)
            )

            stdout_thread.daemon = True
            stderr_thread.daemon = True
            stdout_thread.start()
            stderr_thread.start()

            # Wait for process with timeout
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.terminate()
                return {
                    'success': False,
                    'stdout': '',
                    'stderr': '',
                    'error': f'Command timed out after {timeout} seconds',
                    'returncode': -1
                }

            # Wait for output threads to complete
            stdout_thread.join(1)
            stderr_thread.join(1)

            # Collect all output
            stdout_lines = []
            stderr_lines = []

            while not stdout_queue.empty():
                stdout_lines.append(stdout_queue.get_nowait())
            while not stderr_queue.empty():
                stderr_lines.append(stderr_queue.get_nowait())

            return {
                'success': process.returncode == 0 and not state.error_detected,
                'stdout': '\n'.join(stdout_lines),
                'stderr': '\n'.join(stderr_lines),
                'error': state.error_message if state.error_detected else None,
                'returncode': process.returncode
            }

        except Exception as e:
            self.logger.error(f"Command failed: {str(e)}")
            return {
                'success': False,
                'stdout': '',
                'stderr': str(e),
                'error': str(e),
                'returncode': -1
            }

    def check_process_status(self) -> Dict:
        """Check if process is running correctly"""
        try:
            # First try jlist for detailed status
            jlist = subprocess.run(
                "pm2 jlist",
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if jlist.returncode == 0:
                try:
                    processes = json.loads(jlist.stdout)
                    process = next((p for p in processes if p['name'] == self.name), None)
                    
                    if process:
                        status = process.get('pm2_env', {}).get('status')
                        if status == 'online':
                            return {'success': True}
                        else:
                            return {
                                'success': False,
                                'error': f"Process is in {status} state"
                            }
                except json.JSONDecodeError:
                    pass  # Fall through to pm2 show

            # Fallback to pm2 show
            show = subprocess.run(
                f"pm2 show {self.name}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if show.returncode != 0:
                return {
                    'success': False,
                    'error': f"Failed to get process status: {show.stderr}"
                }

            output = show.stdout.lower()
            if "online" in output:
                return {'success': True}
            elif any(x in output for x in ["errored", "error", "stopped", "exit"]):
                return {
                    'success': False,
                    'error': f"Process is not running: {show.stdout}"
                }

            return {'success': True}

        except Exception as e:
            return {
                'success': False,
                'error': f"Error checking process status: {str(e)}"
            }

    def get_error_details(self) -> str:
        """Get comprehensive error details"""
        details = []
        try:
            # Get PM2 logs
            logs = subprocess.run(
                f"pm2 logs {self.name} --lines 20 --nostream",
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            if logs.returncode == 0:
                details.append("=== Recent Logs ===")
                details.append(logs.stdout)

            # Get process info
            info = subprocess.run(
                f"pm2 show {self.name}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            if info.returncode == 0:
                details.append("\n=== Process Info ===")
                details.append(info.stdout)

            return "\n".join(details) if details else "Could not retrieve error details"
        except Exception as e:
            return f"Error getting details: {str(e)}"

    def cleanup(self):
        """Clean up resources on failure"""
        try:
            # First try graceful stop
            subprocess.run(
                f"pm2 stop {self.name}",
                shell=True,
                check=False,
                timeout=30
            )
            time.sleep(2)  # Give process time to stop
            
            # Then force delete
            subprocess.run(
                f"pm2 delete {self.name}",
                shell=True,
                check=False,
                timeout=30
            )

            # Clean up files with error handling
            paths = [
                Path(f"/home/pm2/pm2-configs/{self.name}.config.js"),
                Path(f"/home/pm2/pm2-processes/{self.name}")
            ]
            
            for path in paths:
                try:
                    if path.exists():
                        if path.is_file():
                            path.unlink()
                        else:
                            shutil.rmtree(path)
                except Exception as e:
                    self.logger.error(f"Failed to remove {path}: {str(e)}")
                    
        except Exception as e:
            self.logger.error(f"Cleanup failed: {str(e)}")