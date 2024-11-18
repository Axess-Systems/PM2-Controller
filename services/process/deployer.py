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

            for directory in [config_dir, process_dir, logs_dir]:
                directory.mkdir(parents=True, exist_ok=True)
                self.logger.debug(f"Created directory: {directory}")

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

            self.logger.debug(f"Config file created at: {config_path}")
            with open(config_path, 'r') as f:
                self.logger.debug(f"Config file contents:\n{f.read()}")

            clean_cmd = f"rm -rf {process_dir}/current {process_dir}/source"
            clean_result = self.run_command(clean_cmd, "Cleanup")
            if not clean_result['success']:
                self.logger.warning(f"Cleanup warning: {clean_result['stderr']}")

            repo_url = self.config_data['repository']['url']
            branch = self.config_data['repository'].get('branch', 'main')

            clone_cmd = f"git clone -b {branch} {repo_url} {process_dir}/source"
            clone_result = self.run_command(clone_cmd, "Git Clone")
            if not clone_result['success']:
                raise PM2CommandError(f"Git clone failed: {clone_result['stderr']}")

            current_dir = process_dir / "current"
            current_dir.mkdir(exist_ok=True)

            copy_cmd = f"cp -r {process_dir}/source/* {current_dir}/"
            copy_result = self.run_command(copy_cmd, "Copy Files")
            if not copy_result['success']:
                raise PM2CommandError(f"File copy failed: {copy_result['stderr']}")

            venv_cmd = f"python3 -m venv {process_dir}/venv"
            venv_result = self.run_command(venv_cmd, "Create venv")
            if not venv_result['success']:
                raise PM2CommandError(f"Virtual environment creation failed: {venv_result['stderr']}")

            if (current_dir / "requirements.txt").exists():
                pip_cmd = f"{process_dir}/venv/bin/pip install -r {current_dir}/requirements.txt"
                pip_result = self.run_command(pip_cmd, "Install Dependencies")
                if not pip_result['success']:
                    raise PM2CommandError(f"Dependencies installation failed: {pip_result['stderr']}")

            # Save the PM2 process list
            save_cmd = "pm2 save"
            save_result = self.run_command(save_cmd, "PM2 Save")
            if not save_result["success"]:
                self.logger.warning(f"PM2 save failed: {save_result['stderr']}")

            # Start the process with PM2
            start_cmd = f"pm2 start {config_path}"
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

    
    def run_command(self, cmd: str, action: str, cwd: str = None, timeout: int = 600) -> Dict:
        try:
            # Special handling for PM2 start command
            if "pm2 start" in cmd:
                cwd = "/home/pm2/pm2-configs"
                config_name = Path(cmd.split()[-1]).name
                process_name = config_name.replace('.config.js', '')
                
                # Run the start command without waiting for output
                subprocess.run(
                    f"pm2 start {config_name}",
                    shell=True,
                    cwd=cwd
                )
                
                # Check process status through pm2 jlist
                try:
                    process_list = json.loads(
                        subprocess.check_output(
                            "pm2 jlist",
                            shell=True,
                            text=True
                        )
                    )
                    
                    process = next((p for p in process_list if p["name"] == process_name), None)
                    if process:
                        status = process.get("pm2_env", {}).get("status")
                        if status == "online":
                            return {"success": True, "stdout": f"Process {process_name} started", "stderr": ""}
                        else:
                            return {"success": False, "stdout": "", "stderr": f"Process status: {status}"}
                    else:
                        return {"success": False, "stdout": "", "stderr": f"Process {process_name} not found"}
                        
                except Exception as e:
                    return {"success": False, "stdout": "", "stderr": f"Failed to verify process status: {str(e)}"}
            
            # Normal command handling for other commands
            self.logger.info(f"Running {action} command: {cmd} from {cwd or 'current directory'}")
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            }
                
        except subprocess.TimeoutExpired as e:
            self.logger.error(f"{action} command timed out after {timeout} seconds")
            return {"success": False, "stdout": "", "stderr": f"Command timed out after {timeout} seconds"}
        except Exception as e:
            self.logger.error(f"Error running {action} command: {e}")
            return {"success": False, "stdout": "", "stderr": str(e)}


    def cleanup(self):
        """Clean up resources on failure"""
        try:
            self.logger.info(f"Starting cleanup for failed deployment of {self.name}")

            pm2_delete = self.run_command(f"{self.config.PM2_BIN} delete {self.name}", "PM2 Delete")
            self.logger.debug(f"PM2 delete result: {pm2_delete}")

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
