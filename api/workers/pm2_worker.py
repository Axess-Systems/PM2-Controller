#!/usr/bin/env python3
# /home/pm2/workers/pm2_worker.py

import os
import sys
import json
import time
import shutil
import logging
from pathlib import Path
from typing import Dict, Optional

class PM2WorkerConfig:
    """Configuration for PM2 Worker"""
    def __init__(self):
        self.BASE_PATH = Path("/home/pm2")
        self.CONFIG_DIR = self.BASE_PATH / "pm2-configs"
        self.PROCESSES_DIR = self.BASE_PATH / "pm2-processes"
        self.LOG_DIR = self.BASE_PATH / "logs"
        
        # Create necessary directories
        for directory in [self.CONFIG_DIR, self.PROCESSES_DIR, self.LOG_DIR]:
            directory.mkdir(parents=True, exist_ok=True)

class PM2Worker:
    def __init__(self):
        self.config = PM2WorkerConfig()
        
    def setup_process(self, process_config: Dict) -> Dict:
        """Set up a new PM2 process"""
        try:
            name = process_config['name']
            
            # Setup process directory structure
            process_dir = self.config.PROCESSES_DIR / name
            venv_path = process_dir / "venv"
            current_dir = process_dir / "current"
            logs_dir = process_dir / "logs"
            
            # Create directories
            for directory in [process_dir, venv_path, current_dir, logs_dir]:
                directory.mkdir(parents=True, exist_ok=True)

            # Clone repository
            repo_url = process_config['repository']['url']
            branch = process_config['repository'].get('branch', 'main')
            os.system(f"git clone -b {branch} {repo_url} {current_dir}")

            # Set up virtual environment
            os.system(f"python3 -m venv {venv_path}")

            # Install dependencies
            requirements_file = current_dir / "requirements.txt"
            if requirements_file.exists():
                os.system(f"{venv_path}/bin/pip install -r {requirements_file}")

            # Generate PM2 config
            config_file = self.generate_pm2_config(process_config, process_dir, venv_path, logs_dir)
            
            # Use PM2's API to start the process
            import pm2.api
            pm2.api.start(str(config_file))  # Use the Python PM2 API instead of command line
            
            return {
                'success': True,
                'message': f"Process {name} setup completed successfully",
                'config_file': str(config_file)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def generate_pm2_config(self, process_config: Dict, process_dir: Path, venv_path: Path, logs_dir: Path) -> Path:
        """Generate PM2 configuration file"""
        name = process_config['name']
        script = process_config.get('script', 'app.py')
        
        config_content = f'''module.exports = {{
    apps: [{{
        name: "{name}",
        script: "{venv_path}/bin/python",
        args: "{script}",
        cwd: "{process_dir}/current",
        env: {json.dumps(process_config.get('env_vars', {}))},
        autorestart: {str(process_config.get('auto_restart', True)).lower()},
        watch: false,
        ignore_watch: ["venv", "*.pyc", "__pycache__", "*.log"],
        max_memory_restart: "1G",
        error_file: "{logs_dir}/{name}-error.log",
        out_file: "{logs_dir}/{name}-out.log",
        merge_logs: true,
        time: true
    }}]
}};'''

        config_file = self.config.CONFIG_DIR / f"{name}.config.js"
        with open(config_file, 'w') as f:
            f.write(config_content)
        
        return config_file

def main():
    """Main worker entry point"""
    if len(sys.argv) != 2:
        print(json.dumps({
            'success': False,
            'error': "Usage: pm2_worker.py <config_file>"
        }))
        sys.exit(1)
    
    try:
        # Load process configuration
        with open(sys.argv[1]) as f:
            process_config = json.load(f)
        
        # Run worker
        worker = PM2Worker()
        result = worker.setup_process(process_config)
        
        # Output result
        print(json.dumps(result))
        sys.exit(0 if result['success'] else 1)
        
    except Exception as e:
        print(json.dumps({
            'success': False,
            'error': str(e)
        }))
        sys.exit(1)

if __name__ == "__main__":
    main()