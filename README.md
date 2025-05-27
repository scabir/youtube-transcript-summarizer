# YouTube Transcript Summarizer

A tool that generates structured summaries of YouTube videos using OpenAI's GPT models.

## Configuration

You need to have a file called `config.yaml` in the `config` directory. However, there is no `config.yaml` file included in the repository for security reasons. You need to create your own `config.yaml` file in the `config` directory. Use the template file `__config_template.yaml` as a starting point and replace the placeholder values with your actual configuration. You can rename and use it. config.yaml file will be excluded from the repository.

```yaml
openai:
  api_key: "asdfasdfasdf"
  default_model: "gpt-3.5-turbo"
  max_tokens: 4096

paths:
  results_folder: "../results"

language:
  default: "en"
  supported: ["en", "tr", "es", "fr", "de"]
```

```python
# OpenAI API Configuration
# IMPORTANT: Replace the placeholder with your actual OpenAI API key
OPENAI_API_KEY = ""  # Your OpenAI API key here
DEFAULT_MODEL = 'gpt-3.5-turbo'
MAX_TOKENS = 4096

# Directory configuration
RESULTS_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'results')
```

## Usage

To use the tool, run the following command:

```bash
python app.py --url <YOUR_YOUTUBE_VIDEO_URL>
```

Replace `<YOUR_YOUTUBE_VIDEO_URL>` with the URL of the YouTube video you want to summarize.

For example:

```bash
python app.py --url https://www.youtube.com/watch?v=xxyyzz --language en
```

This will generate a markdown file in the `results` directory with the summary of the video. You can change the `results_folder` in the `config.yaml` file to change the directory where the markdown file is saved.

## License

MIT License

## Author

Suleyman Cabir Ataman, PhD
