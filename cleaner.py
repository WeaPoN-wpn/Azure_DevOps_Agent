# cleaner.py
# Script to clean Azure DevOps work item data by removing HTML tags and normalizing text

import json
import re
import os
from bs4 import BeautifulSoup
from pathlib import Path
import dotenv

# Load environment variables
dotenv.load_dotenv()

def clean_html(html_content):
    """
    Remove HTML tags and clean up text content.
    
    Args:
        html_content (str): HTML content to clean
        
    Returns:
        str: Cleaned plain text
    """
    if not html_content or html_content.strip() == "":
        return ""
    
    # Parse HTML
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.decompose()
    
    # Get text content
    text = soup.get_text()
    
    # Clean up whitespace
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = ' '.join(chunk for chunk in chunks if chunk)
    
    return text

def remove_mentions(text):
    """
    Remove @mentions from text while preserving readability.
    
    Args:
        text (str): Text containing mentions
        
    Returns:
        str: Text with mentions removed
    """
    # Remove @mentions but keep the name for context
    mention_pattern = r'<a href="#"[^>]*data-vss-mention[^>]*>@([^<]+)</a>'
    text = re.sub(mention_pattern, r'\1', text)
    
    # Remove any remaining HTML-like patterns
    text = re.sub(r'<[^>]+>', '', text)
    
    return text.strip()

def clean_workitem_data(workitems):
    """
    Clean all work item data by removing HTML tags and normalizing content.
    
    Args:
        workitems (list): List of work item dictionaries
        
    Returns:
        list: List of cleaned work item dictionaries
    """
    cleaned_workitems = []
    
    for item in workitems:
        cleaned_item = item.copy()
        
        # Clean description
        if 'description' in cleaned_item:
            cleaned_item['description'] = clean_html(cleaned_item['description'])
            cleaned_item['description'] = remove_mentions(cleaned_item['description'])
        
        # Clean comments
        if 'comments' in cleaned_item:
            cleaned_comments = []
            for comment in cleaned_item['comments']:
                cleaned_comment = clean_html(comment)
                cleaned_comment = remove_mentions(cleaned_comment)
                if cleaned_comment.strip():  # Only keep non-empty comments
                    cleaned_comments.append(cleaned_comment)
            cleaned_item['comments'] = cleaned_comments
        
        # Create combined clean text for better searchability
        clean_text_parts = []
        
        if cleaned_item.get('title'):
            clean_text_parts.append(f"Title: {cleaned_item['title']}")
        
        if cleaned_item.get('description'):
            clean_text_parts.append(f"Description: {cleaned_item['description']}")
        
        if cleaned_item.get('comments'):
            comments_text = ' '.join(cleaned_item['comments'])
            if comments_text.strip():
                clean_text_parts.append(f"Comments: {comments_text}")
        
        if cleaned_item.get('state'):
            clean_text_parts.append(f"State: {cleaned_item['state']}")
        
        if cleaned_item.get('assigned_to'):
            clean_text_parts.append(f"Assigned to: {cleaned_item['assigned_to']}")
        
        # TODO: Process image files when image processing is implemented
        # if cleaned_item.get('image_files'):
        #     # Future: Extract text from images or include image descriptions
        #     pass
        
        cleaned_item['clean_text'] = '\n'.join(clean_text_parts)
        cleaned_workitems.append(cleaned_item)
    
    return cleaned_workitems

def main():
    """Main function to clean work item data."""
    input_file = Path("storage/workitem_details.json")
    output_file = Path("stage/cleaned_workitems.json")
    
    # Ensure stage directory exists
    output_file.parent.mkdir(exist_ok=True)
    
    if not input_file.exists():
        print(f"Error: Input file {input_file} not found.")
        return
    
    print(f"Loading work items from {input_file}...")
    
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            workitems = json.load(f)
        
        print(f"Loaded {len(workitems)} work items.")
        
        # Clean the data
        print("Cleaning work item data...")
        cleaned_workitems = clean_workitem_data(workitems)
        
        # Save cleaned data
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(cleaned_workitems, f, indent=2, ensure_ascii=False)
        
        print(f"Cleaned work items saved to {output_file}")
        print(f"Successfully processed {len(cleaned_workitems)} work items.")
        
        # Display sample of cleaned data
        if cleaned_workitems:
            print("\nSample cleaned work item:")
            print(f"ID: {cleaned_workitems[0]['id']}")
            print(f"Title: {cleaned_workitems[0]['title']}")
            print(f"Clean text preview: {cleaned_workitems[0]['clean_text'][:200]}...")
    
    except Exception as e:
        print(f"Error processing work items: {e}")

if __name__ == "__main__":
    main()
