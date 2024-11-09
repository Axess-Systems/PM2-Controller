import os
import json
from pathlib import Path
from typing import Dict, Optional
import logging
from core.config import Config
from core.exceptions import ProcessNotFoundError, ProcessAlreadyExistsError
from services.pm2 import PM2Service

class ProcessManager:
    """Service for managing PM2 processes and their configurations"""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.pm2_service = PM2Service(config, logger)
    
    def _create_pm2_config(self, process_name: str, config_data: Dict) -> Path:
        """Create PM2 config file for a process"""
        config_path = self.config.PM2_CONFIG_DIR / f"{process_name}.config.js"
        
        pm2_config = {
            "name": process_name,
            "script": config_data['python']['run_script'],
            "args": config_data['python'].get('arguments', ''),
            "instances": config_data['pm2'].get('instances', 1),
            "exec_mode": config_data['pm2'].get('exec_mode', 'fork'),
            "cron_restart": config_data['pm2'].get('cron_restart'),
            "watch": config_data['pm2'].get('watch', False),
            "autorestart": config_data['pm2'].get('autorestart', True)
        }
        
        self.logger.debug(f"Creating PM2 config at {config_path}")
        with open(config_path, 'w') as f:
            f.write("module.exports = {\n")
            f.write("  apps: [\n")
            f.write("    " + json.dumps(pm2_config, indent=2).replace('"', "'") + "\n")
            f.write("  ]\n")
            f.write("};\n")
        
        return config_path
    
    def _create_python_config(self, process_name: str, config_data: Dict) -> Path:
        """Create Python INI config file for a process"""
        config_path = self.config.PYTHON_WRAPPER_DIR / f"{process_name}.ini"
        
        self.logger.debug(f"Creating Python config at {config_path}")
        with open(config_path, 'w') as f:
            # Repository section
            f.write("[repository]\n")
            f.write(f"url = {config_data['repository']['url']}\n")
            f.write(f"project_dir = {config_data['repository']['project_dir']}\n")
            f.write(f"branch = {config_data['repository']['branch']}\n\n")
            
            # Dependencies section
            f.write("[dependencies]\n")
            f.write(f"requirements_file = {config_data['python'].get('requirements_file', 'requirements.txt')}\n")
            f.write(f"run_script = {config_data['python'].get('run_script', 'app.py')}\n")
            f.write(f"arguments = {config_data['python'].get('arguments', '')}\n\n")
            
            # Variables section if present
            if 'variables' in config_data['python']:
                f.write("[variables]\n")
                for key, value in config_data['python']['variables'].items():
                    f.write(f"{key} = {value}\n")
                f.write("\n")
            
            # SMTP section if enabled
            if config_data['python'].get('smtp', {}).get('enabled'):
                f.write("[smtp]\n")
                f.write("enabled = true\n\n")
                
        return config_path
    
    def create_process(self, config_data: Dict) -> Dict:
        """Create a new PM2 process with configuration"""
        process_name = config_data['name']
        
        try:
            # Check if process already exists
            if process_name in [p['name'] for p in self.pm2_service.list_processes()]:
                raise ProcessAlreadyExistsError(f"Process {process_name} already exists")
            
            # Create configuration files
            pm2_config_path = self._create_pm2_config(process_name, config_data)
            python_config_path = self._create_python_config(process_name, config_data)
            
            # Start the process
            original_dir = os.getcwd()
            try:
                os.chdir(self.config.PYTHON_WRAPPER_DIR)
                self.pm2_service.execute_command(f"start {pm2_config_path}")
            finally:
                os.chdir(original_dir)
            
            return {
                "message": f"Process {process_name} created successfully",
                "config_files": {
                    "pm2_config": str(pm2_config_path),
                    "python_config": str(python_config_path)
                }
            }
            
        except Exception as e:
            self.logger.error(f"Failed to create process {process_name}: {str(e)}")
            raise
    
    def update_process(self, process_name: str, config_data: Dict) -> Dict:
        """Update an existing process configuration"""
        try:
            # Check if process exists
            if process_name not in [p['name'] for p in self.pm2_service.list_processes()]:
                raise ProcessNotFoundError(f"Process {process_name} not found")
            
            # Update configuration files
            pm2_config_path = self._create_pm2_config(process_name, config_data)
            python_config_path = self._create_python_config(process_name, config_data)
            
            # Restart the process
            self.pm2_service.reload_process(process_name)
            
            return {
                "message": f"Process {process_name} updated successfully",
                "config_files": {
                    "pm2_config": str(pm2_config_path),
                    "python_config": str(python_config_path)
                }
            }
            
        except Exception as e:
            self.logger.error(f"Failed to update process {process_name}: {str(e)}")
            raise
    
    def delete_process(self, process_name: str) -> Dict:
        """Delete a process and its configuration files"""
        try:
            # Stop and delete the process
            self.pm2_service.delete_process(process_name)
            
            # Remove configuration files
            pm2_config = self.config.PM2_CONFIG_DIR / f"{process_name}.config.js"
            python_config = self.config.PYTHON_WRAPPER_DIR / f"{process_name}.ini"
            
            if pm2_config.exists():
                pm2_config.unlink()
            if python_config.exists():
                python_config.unlink()
            
            return {
                "message": f"Process {process_name} and its configuration files deleted successfully"
            }
            
        except Exception as e:
            self.logger.error(f"Failed to delete process {process_name}: {str(e)}")
            raise