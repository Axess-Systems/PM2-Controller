from multiprocessing import Queue
from queue import Empty
from typing import Dict
import logging
import threading
from pathlib import Path
from core.config import Config
from core.exceptions import ProcessNotFoundError, ProcessAlreadyExistsError, PM2CommandError
from services.pm2.service import PM2Service
from .deployer import ProcessDeployer

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
        try:
            process = self.pm2_service.get_process(name)
            if process.get('pm2_env', {}).get('status') == 'online':
                raise PM2CommandError(
                    f"Process {name} is running. Stop it first with 'pm2 stop {name}'"
                )
            
            self.pm2_service.commands.execute(f"delete {name}")
            
            # Cleanup files
            for path in [
                Path(f"/home/pm2/pm2-configs/{name}.config.js"),
                Path(f"/home/pm2/pm2-processes/{name}")
            ]:
                if path.exists():
                    path.unlink() if path.is_file() else shutil.rmtree(path)
            
            return {"message": f"Process {name} deleted successfully"}
            
        except Exception as e:
            self.logger.error(f"Failed to delete {name}: {str(e)}")
            raise