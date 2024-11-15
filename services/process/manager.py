import time
import json
import subprocess
import threading
import shutil
from pathlib import Path
from typing import Dict
import logging
from core.config import Config
from core.exceptions import ProcessNotFoundError, ProcessAlreadyExistsError, PM2CommandError
from services.pm2.service import PM2Service

class ProcessManager:
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.pm2_service = PM2Service(config, logger)
        self._command_locks = {}
        self._global_lock = threading.Lock()
        self._lock_timeouts = {}

    def create_process(self, config_data: Dict, timeout: int = 600) -> Dict:
        name = config_data['name']
        
        if Path(f"/home/pm2/pm2-configs/{name}.config.js").exists():
            raise ProcessAlreadyExistsError(f"Process {name} already exists")
        
        result_queue = Queue()
        deployer = ProcessDeployer(
            config=self.config,
            name=name,
            config_data=config_data,
            result_queue=result_queue,
            logger=self.logger
        )
        
        try:
            deployer.start()
            result = result_queue.get(timeout=timeout)
            
            if not result["success"]:
                raise PM2CommandError(result["error"])
                
            return result
            
        except Empty:
            deployer.terminate()
            raise PM2CommandError(f"Deployment timed out after {timeout} seconds")
        finally:
            deployer.join()

    def delete_process(self, name: str) -> Dict:
        """Delete a process and its configuration"""
        try:
            config_path = Path(f"/home/pm2/pm2-configs/{name}.config.js")
            process_dir = Path(f"/home/pm2/pm2-processes/{name}")
                
            # Try to delete from PM2 if running
            try:
                process_info = json.loads(subprocess.run(
                    f"{self.config.PM2_BIN} jlist",
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=True
                ).stdout)
                
                process = next((p for p in process_info if p['name'] == name), None)
                if process:
                    if process.get('pm2_env', {}).get('status') == 'online':
                        raise PM2CommandError(
                            f"Process {name} is currently running. Stop it first using 'pm2 stop {name}'"
                        )
                    # Process exists in PM2, delete it
                    subprocess.run(
                        f"pm2 delete {name}",
                        shell=True,
                        check=True,
                        capture_output=True
                    )
            except (subprocess.CalledProcessError, json.JSONDecodeError):
                self.logger.warning(f"Process {name} was not running in PM2")
                
            # Always cleanup files
            if config_path.exists():
                config_path.unlink()
            if process_dir.exists():
                shutil.rmtree(process_dir)
                
            return {
                "message": f"Process {name} deleted successfully"
            }
                
        except Exception as e:
            self.logger.error(f"Failed to delete process {name}: {str(e)}")
            raise