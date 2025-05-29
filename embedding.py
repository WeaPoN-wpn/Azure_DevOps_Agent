# embedding.py
# Script to generate embeddings for chunked Azure DevOps work item data

import json
import os
import sys
import time
from pathlib import Path
import dotenv
from openai import AzureOpenAI
from openai import APIConnectionError, RateLimitError, APIStatusError

# Load environment variables
dotenv.load_dotenv()

# Azure OpenAI configuration
AZURE_OPENAI_ENDPOINT = os.getenv('AZURE_OPENAI_ENDPOINT')
AZURE_OPENAI_API_KEY = os.getenv('AZURE_OPENAI_API_KEY')
AZURE_OPENAI_API_VERSION = os.getenv('AZURE_OPENAI_API_VERSION')
EMBEDDING_MODEL_DEPLOYMENT_NAME = os.getenv('EMBEDDING_MODEL_DEPLOYMENT_NAME')

# Initialize Azure OpenAI client
client = AzureOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_API_KEY,
    api_version=AZURE_OPENAI_API_VERSION
)

def get_text_embedding(text: str, model_deployment_name: str = EMBEDDING_MODEL_DEPLOYMENT_NAME) -> list[float] | None:
    """
    Generate an embedding for a given text chunk using Azure OpenAI.
    
    Args:
        text (str): The text content to embed
        model_deployment_name (str): The deployment name of the embedding model
        
    Returns:
        list[float] | None: A list of floats representing the embedding vector, or None if error occurs
    """
    # Clean text for embedding models
    text = text.replace("\n", " ").strip()
    
    if not text:
        print("Warning: Empty text provided for embedding")
        return None
    
    try:
        response = client.embeddings.create(
            input=[text],
            model=model_deployment_name
        )
        return response.data[0].embedding
    except APIConnectionError as e:
        print(f"Connection error: {e}")
        print("Please check your AZURE_OPENAI_ENDPOINT and network connection.")
    except RateLimitError as e:
        print(f"Rate limit exceeded: {e}")
        print("Waiting before retry...")
        time.sleep(10)  # Wait 10 seconds before retry
        return None
    except APIStatusError as e:
        print(f"Azure OpenAI API error: {e.status_code} - {e.response}")
        print("Please check your API key, version, and model deployment name.")
    except Exception as e:
        print(f"Unexpected error during embedding generation: {e}")
    return None

def generate_embeddings_with_retry(text: str, max_retries: int = 3) -> list[float] | None:
    """
    Generate embedding with retry logic for rate limiting.
    
    Args:
        text (str): Text to embed
        max_retries (int): Maximum number of retry attempts
        
    Returns:
        list[float] | None: Embedding vector or None if all retries failed
    """
    for attempt in range(max_retries):
        embedding = get_text_embedding(text)
        if embedding is not None:
            return embedding
        
        if attempt < max_retries - 1:
            wait_time = (attempt + 1) * 5  # Progressive backoff
            print(f"Retrying in {wait_time} seconds... (attempt {attempt + 2}/{max_retries})")
            time.sleep(wait_time)
    
    return None

def generate_embeddings_for_chunks(chunks):
    """
    Generate embeddings for all chunks with progress tracking.
    
    Args:
        chunks (list): List of chunk dictionaries
        
    Returns:
        list: List of chunks with embeddings added
    """
    embeddings_data = []
    failed_chunks = []
    
    print(f"Generating embeddings for {len(chunks)} chunks...")
    
    for i, chunk in enumerate(chunks):
        print(f"Processing chunk {i+1}/{len(chunks)} (Work Item {chunk['workitem_id']})...")
        
        # Generate embedding
        embedding = generate_embeddings_with_retry(chunk['content'])
        
        if embedding is not None:
            # Create embedding data structure
            embedding_data = {
                'chunk_id': chunk['chunk_id'],
                'content': chunk['content'],
                'workitem_id': chunk['workitem_id'],
                'embedding': embedding,
                'metadata': chunk['metadata']
            }
            embeddings_data.append(embedding_data)
        else:
            print(f"Failed to generate embedding for chunk {chunk['chunk_id']}")
            failed_chunks.append(chunk['chunk_id'])
        
        # Add small delay to avoid rate limiting
        if i < len(chunks) - 1:
            time.sleep(0.5)
    
    if failed_chunks:
        print(f"\nWarning: Failed to generate embeddings for {len(failed_chunks)} chunks:")
        for chunk_id in failed_chunks:
            print(f"  - {chunk_id}")
    
    return embeddings_data

def save_embeddings_data(embeddings_data, output_file):
    """
    Save embeddings data to JSON file.
    
    Args:
        embeddings_data (list): List of embedding dictionaries
        output_file (Path): Output file path
    """
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(embeddings_data, f, indent=2, ensure_ascii=False)
        print(f"Embeddings saved to {output_file}")
    except Exception as e:
        print(f"Error saving embeddings: {e}")

def load_existing_embeddings(output_file):
    """
    Load existing embeddings to support incremental processing.
    
    Args:
        output_file (Path): Path to existing embeddings file
        
    Returns:
        dict: Dictionary of chunk_id -> embedding_data
    """
    existing_embeddings = {}
    
    if output_file.exists():
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
            
            for item in existing_data:
                existing_embeddings[item['chunk_id']] = item
            
            print(f"Loaded {len(existing_embeddings)} existing embeddings")
        except Exception as e:
            print(f"Warning: Could not load existing embeddings: {e}")
    
    return existing_embeddings

def main():
    """Main function to generate embeddings for chunked work item data."""
    input_file = Path("stage/chunked_workitems.json")
    output_file = Path("stage/workitem_embeddings.json")
    
    # Ensure stage directory exists
    output_file.parent.mkdir(exist_ok=True)
    
    if not input_file.exists():
        print(f"Error: Input file {input_file} not found.")
        print("Please run chunker.py first to generate chunked work items.")
        return
    
    # Validate environment variables
    if not all([AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, EMBEDDING_MODEL_DEPLOYMENT_NAME]):
        print("Error: Missing required Azure OpenAI environment variables.")
        print("Please check your .env file contains:")
        print("- AZURE_OPENAI_ENDPOINT")
        print("- AZURE_OPENAI_API_KEY")
        print("- EMBEDDING_MODEL_DEPLOYMENT_NAME")
        return
    
    print(f"Loading chunked work items from {input_file}...")
    
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            chunks = json.load(f)
        
        print(f"Loaded {len(chunks)} chunks.")
        
        # Load existing embeddings for incremental processing
        existing_embeddings = load_existing_embeddings(output_file)
        
        # Filter out chunks that already have embeddings
        new_chunks = [chunk for chunk in chunks if chunk['chunk_id'] not in existing_embeddings]
        
        if not new_chunks:
            print("All chunks already have embeddings. No new processing needed.")
            return
        
        print(f"Processing {len(new_chunks)} new chunks (skipping {len(existing_embeddings)} existing)...")
        
        # Generate embeddings for new chunks
        new_embeddings_data = generate_embeddings_for_chunks(new_chunks)
        
        # Combine with existing embeddings
        all_embeddings_data = list(existing_embeddings.values()) + new_embeddings_data
        
        # Save all embeddings
        save_embeddings_data(all_embeddings_data, output_file)
        
        print(f"\nEmbedding generation complete!")
        print(f"Total embeddings: {len(all_embeddings_data)}")
        print(f"New embeddings generated: {len(new_embeddings_data)}")
        print(f"Failed embeddings: {len(new_chunks) - len(new_embeddings_data)}")
        
        # Display sample embedding info
        if new_embeddings_data:
            sample = new_embeddings_data[0]
            print(f"\nSample embedding:")
            print(f"Chunk ID: {sample['chunk_id']}")
            print(f"Work Item ID: {sample['workitem_id']}")
            print(f"Embedding dimension: {len(sample['embedding'])}")
            print(f"Content preview: {sample['content'][:150]}...")
            
        # TODO: Process image embeddings when image processing is implemented
        # if image_files_found:
        #     print("\nNote: Image files detected but not processed.")
        #     print("Image embedding functionality will be implemented in future updates.")
    
    except Exception as e:
        print(f"Error processing embeddings: {e}")

if __name__ == "__main__":
    main()
