from flask_restx import fields

def create_error_models(api):
    """Create and register error response models"""
    
    error_model = api.model('Error', {
        'error': fields.String(description='Error message'),
        'error_type': fields.String(description='Error type'),
        'timestamp': fields.DateTime(description='Error timestamp'),
        'details': fields.Raw(description='Additional error details')
    })

    return error_model