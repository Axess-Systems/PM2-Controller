# services/pm2/service.py
import subprocess
import json
import time
import logging
from pathlib import Path
from typing import List, Dict, Optional
from core.config import Config
from core.exceptions import PM2Error, ProcessNotFoundError
from .config import PM2Config

class PM2Service:
    """Service for interacting with PM2 process manager with improved error handling"""
    
    def __init__(self, config: Config, logger: logging.Logger):
        """Initialize PM2Service
        
        Args:
            config: Application configuration instance
            logger: Logger instance for logging PM2 operations
        """
        self.config = config
        self.logger = logger
        self.config_generator = PM2Config(logger=logger)
        self._verify_pm2_installation()
    
    def _verify_pm2_installation(self):
        """Verify PM2 is installed and accessible"""
        try:
            result = subprocess.run(
                f"{self.config.PM2_BIN} --version",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                self.logger.error(f"PM2 version check failed: {result.stderr}")
                raise PM2Error("PM2 is not properly installed or accessible")
            self.logger.info(f"PM2 version: {result.stdout.strip()}")
        except Exception as e:
            self.logger.error(f"PM2 verification failed: {str(e)}")
            raise PM2Error(f"PM2 verification failed: {str(e)}")

    def generate_config(self, name: str, repo_url: str, script: str = 'main.py', 
                       branch: str = "main", cron: str = None, 
                       auto_restart: bool = True, 
                       env_vars: Dict[str, str] = None) -> Path:
        """Generate PM2 configuration file using the config generator"""
        try:
            return self.config_generator.generate_config(
                name=name,
                repo_url=repo_url,
                script=script,
                branch=branch,
                cron=cron,
                auto_restart=auto_restart,
                env_vars=env_vars
            )
        except Exception as e:
            self.logger.error(f"Failed to generate config for {name}: {str(e)}")
            raise PM2Error(f"Config generation failed: {str(e)}")
    
    def list_processes(self) -> List[Dict]:
        """Get list of all PM2 processes with improved error handling"""
        try:
            result = subprocess.run(
                f"{self.config.PM2_BIN} jlist",
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.config.COMMAND_TIMEOUT
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() or "Unknown error"
                self.logger.error(f"PM2 list processes failed: {error_msg}")
                raise PM2Error(f"Failed to list processes: {error_msg}")
            
            try:
                processes = json.loads(result.stdout)
                return processes
            except json.JSONDecodeError as e:
                self.logger.error(f"Failed to parse PM2 process list: {str(e)}")
                raise PM2Error(f"Invalid PM2 process list format: {str(e)}")
                
        except subprocess.TimeoutExpired:
            error_msg = f"PM2 command timed out after {self.config.COMMAND_TIMEOUT} seconds"
            self.logger.error(error_msg)
            raise PM2Error(error_msg)
            
        except Exception as e:
            self.logger.error(f"Unexpected error listing processes: {str(e)}")
            raise PM2Error(f"Failed to list processes: {str(e)}")
            
    def get_process(self, name: str) -> Dict:
        """Get details of a specific process with improved error handling"""
        try:
            processes = self.list_processes()
            process = next((p for p in processes if p['name'] == name), None)
            
            if not process:
                raise ProcessNotFoundError(f"Process {name} not found")
                
            return process
            
        except ProcessNotFoundError:
            raise
        except Exception as e:
            self.logger.error(f"Error getting process {name}: {str(e)}")
            raise PM2Error(f"Failed to get process details: {str(e)}")

    def run_command(self, cmd: str, timeout: Optional[int] = None) -> Dict:
        """Run a PM2 command with proper error handling and timeout"""
        try:
            timeout = timeout or self.config.COMMAND_TIMEOUT
            self.logger.debug(f"Running PM2 command: {cmd}")
            
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            # Log command output for debugging
            if result.stdout:
                self.logger.debug(f"Command stdout: {result.stdout.strip()}")
            if result.stderr:
                self.logger.debug(f"Command stderr: {result.stderr.strip()}")
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() or "Unknown error"
                self.logger.error(f"PM2 command failed: {error_msg}")
                raise PM2Error(f"Command failed: {error_msg}")
                
            return {
                'success': True,
                'output': result.stdout.strip(),
                'command': cmd
            }
            
        except subprocess.TimeoutExpired:
            error_msg = f"Command timed out after {timeout} seconds"
            self.logger.error(error_msg)
            raise PM2Error(error_msg)
            
        except Exception as e:
            self.logger.error(f"Command execution failed: {str(e)}")
            raise PM2Error(f"Command failed: {str(e)}")

    def deploy_process(self, process_name: str, action: str = "update") -> Dict:
        """Deploy or update a process using PM2 deploy command
        
        Args:
            process_name: Name of the process to deploy/update
            action: Deploy action (update, setup, revert)
            
        Returns:
            Dict containing deployment results
            
        Raises:
            ProcessNotFoundError: If process doesn't exist
            PM2Error: If deployment fails
        """
        try:
            config_file = Path(f"/home/pm2/pm2-configs/{process_name}.config.js")
            if not config_file.exists():
                raise ProcessNotFoundError(f"Config file not found for {process_name}")
            
            # Run deployment command
            cmd = f"pm2 deploy {config_file} production {action} --force"
            deploy_result = self.run_command(cmd, timeout=300)
            
            # Start/reload the process
            start_result = self.run_command(f"pm2 start {config_file}", timeout=60)
            
            # Save PM2 process list
            save_result = self.run_command("pm2 save", timeout=30)
            
            return {
                'success': True,
                'deploy_output': deploy_result.get('output'),
                'start_output': start_result.get('output'),
                'save_output': save_result.get('output')
            }
            
        except ProcessNotFoundError:
            raise
        except Exception as e:
            self.logger.error(f"Deployment failed: {str(e)}")
            raise PM2Error(f"Deployment failed: {str(e)}")