import openai
import os
from config_loader import load_config

config = load_config()

OPENAI_CONFIG = config['openai']
RESULTS_FOLDER = config['paths']['results_folder']
DEFAULT_MODEL = OPENAI_CONFIG['default_model']
MAX_TOKENS = OPENAI_CONFIG['max_tokens']

def generate_filename(video_title, video_id):
    """Generate a filename using video title and ID."""
    if video_title == video_id:
        return os.path.join(RESULTS_FOLDER, f"{video_id}.md")
    
    clean_title = ''.join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in video_title)
    clean_title = clean_title.strip().replace(' ', '_')
    
    filename = f"{clean_title}__{video_id}.md"
    return os.path.join(RESULTS_FOLDER, filename)

def generate_structure(transcript, output_language):
    """Generate initial structure using OpenAI."""
    client = openai.OpenAI(api_key=OPENAI_CONFIG['api_key'])
    
    prompt = f"""
    Analyze the following video transcript and propose a structured outline. The output will be in {output_language} language.
    
    Transcript: {transcript}
    
    Please provide:
    1. A clear, descriptive title
    2. Main sections/topics
    3. Key points under each section
    
    
    """
    
    try:
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "You are a professional content writer who provides comprehensive and detailed responses." },
                {"role": "user", "content": prompt}
            ],
            max_tokens=MAX_TOKENS,
            temperature=0.7,
            top_p=0.9
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error generating structure: {str(e)}")
        return None

def generate_detailed_content(transcript, structure, output_language):
    """Generate detailed content for each section."""
    client = openai.OpenAI(api_key=OPENAI_CONFIG['api_key'])
    
    prompt = f"""
    Using the following transcript and proposed structure, generate detailed content. The output will be in {output_language} language.
    
    Structure:
    {structure}
    
    Transcript: {transcript}
    
    For each section, create a comprehensive and detailed explanation drawing from the transcript.
    Please provide:
    1. A thorough analysis of the key points
    2. Examples and supporting evidence from the transcript
    3. Context and implications of the information
    4. Any relevant background information
    
    Ensure the content is well-organized, informative, and follows the markdown structure.
    Aim for a detailed and comprehensive response that captures all important aspects of the content.
    """
    
    try:
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "You are a professional content writer who provides comprehensive and detailed responses."},
                {"role": "system", "content": "Do not hallucinate and never write meaningless content." },
                {"role": "system", "content": "Feel free to use maximum tokens if needed, summarize as detailed as you can." },
                {"role": "system", "content": "Respond in a markdown-friendly format." },                
                {"role": "user", "content": prompt}
            ],
            max_tokens=MAX_TOKENS,  
            temperature=0.7,
            top_p=0.9,  
            frequency_penalty=0.2,  
            presence_penalty=0.2  
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating detailed content: {e}")
        return None
