import os
import yaml
from pathlib import Path

def load_config():
    config_path = Path(__file__).parent.parent / 'config' / 'config.yaml'
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found at {config_path}")

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    # Convert relative paths to absolute paths
    config['paths']['results_folder'] = str(
        Path(config_path.parent.parent) / config['paths']['results_folder']
    )

    return config
