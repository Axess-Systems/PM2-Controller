# /core/exceptions.py

class PM2Error(Exception):
    """Base exception for PM2 related errors"""
    pass

class ProcessNotFoundError(PM2Error):
    """Raised when a PM2 process is not found"""
    pass

class ProcessAlreadyExistsError(PM2Error):
    """Raised when trying to create a process that already exists"""
    pass

class PM2CommandError(PM2Error):
    """Raised when a PM2 command fails"""
    pass

class PM2TimeoutError(PM2Error):
    """Raised when a PM2 command times out"""
    pass

def parse_pm2_error(error_message: str) -> Exception:
    """Parse PM2 error messages and return appropriate exception"""
    error_lower = error_message.lower()
    if "process not found" in error_lower:
        return ProcessNotFoundError(error_message)
    elif "already exists" in error_lower:
        return ProcessAlreadyExistsError(error_message)
    else:
        return PM2CommandError(error_message)