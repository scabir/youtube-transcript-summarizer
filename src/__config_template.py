import os

# OpenAI API Configuration
# IMPORTANT: Replace these with your actual OpenAI API credentials
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', "")
DEFAULT_MODEL = 'gpt-3.5-turbo'
MAX_TOKENS = 4096

OPENAI_CONFIG = {
    'api_key': OPENAI_API_KEY
}

# Directory for saving results
RESULTS_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'results')
