
import bleach

def sanitize_input(value):
    if isinstance(value, str):
        return bleach.clean(value)
    elif isinstance(value, dict):
        return {k: sanitize_input(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [sanitize_input(item) for item in value]
    return value
