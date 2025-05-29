# chunker.py
# Script to chunk cleaned Azure DevOps work item data for embedding

import json
import os
import sys
from pathlib import Path
import dotenv
import tiktoken

def get_tokenizer(model_name="cl100k_base"):
    """Returns a tokenizer for a given model name."""
    try:
        tokenizer = tiktoken.get_encoding(model_name)
    except Exception:
        # Fallback for models not directly mapped or if model_name is a deployment name
        tokenizer = tiktoken.get_encoding("cl100k_base")
    return tokenizer

class RecursiveCharacterTextSplitter:
    """
    Splits text into chunks recursively using a list of separators.
    Inspired by LangChain's RecursiveCharacterTextSplitter.
    """
    def __init__(self, chunk_size, chunk_overlap, separators=None, encoding_name="cl100k_base"):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        # Default separators for code and text
        self.separators = separators or ["\n\n", "\n", " ", "", ""]
        self.tokenizer = get_tokenizer(encoding_name)

    def _split_text(self, text, separators):
        """Recursively splits text based on separators."""
        if not separators:
            # If no separators left, split by individual characters (last resort)
            return [text[i:i + self.chunk_size] for i in range(0, len(text), self.chunk_size - self.chunk_overlap)]

        current_separator = separators[0]
        other_separators = separators[1:]

        if current_separator == "": # Split by character if empty separator
            if len(self.tokenizer.encode(text)) <= self.chunk_size:
                return [text]
            else:
                # Fallback to character-level split if no other separator works
                # and text is still too large
                tokens = self.tokenizer.encode(text)
                chunks = []
                for i in range(0, len(tokens), self.chunk_size - self.chunk_overlap):
                    chunk_tokens = tokens[i : i + self.chunk_size]
                    chunks.append(self.tokenizer.decode(chunk_tokens))
                return chunks

        parts = text.split(current_separator)
        chunks = []
        for i, part in enumerate(parts):
            if not part:
                continue
            # If part is too large, recursively split it
            if len(self.tokenizer.encode(part)) > self.chunk_size:
                chunks.extend(self._split_text(part, other_separators))
            else:
                # Add part to current chunk, handling overlap
                if not chunks or len(self.tokenizer.encode(chunks[-1] + current_separator + part)) > self.chunk_size:
                    chunks.append(part)
                else:
                    # Append to last chunk if it fits, respecting overlap
                    # This is a simplified overlap handling. More robust would rebuild from tokens.
                    last_chunk_tokens = self.tokenizer.encode(chunks[-1])
                    part_tokens = self.tokenizer.encode(part)
                    if len(last_chunk_tokens) + len(part_tokens) + len(self.tokenizer.encode(current_separator)) <= self.chunk_size:
                        chunks[-1] += current_separator + part
                    else:
                        # If adding the whole part makes it too big,
                        # try to add an overlapping portion
                        overlap_text = self.tokenizer.decode(last_chunk_tokens[-(self.chunk_overlap):])
                        if len(self.tokenizer.encode(overlap_text + current_separator + part)) <= self.chunk_size:
                            chunks.append(overlap_text + current_separator + part)
                        else:
                            chunks.append(part)

        # Refine chunks to ensure overlap and size
        final_chunks = []
        for i in range(len(chunks)):
            current_chunk = chunks[i]
            if not final_chunks:
                final_chunks.append(current_chunk)
            else:
                # Create overlap by taking the end of the previous chunk
                prev_chunk_tokens = self.tokenizer.encode(final_chunks[-1])
                overlap_tokens = prev_chunk_tokens[max(0, len(prev_chunk_tokens) - self.chunk_overlap):]
                overlap_text = self.tokenizer.decode(overlap_tokens)

                combined_text = overlap_text + current_separator + current_chunk if overlap_text else current_chunk

                # Ensure the combined chunk is within size limits, otherwise just add current_chunk
                if len(self.tokenizer.encode(combined_text)) <= self.chunk_size:
                    final_chunks.append(combined_text)
                else:
                    final_chunks.append(current_chunk) # Add current chunk as is if combined is too big

        # One final pass to ensure no chunks exceed size and add overlap
        re_split_chunks = []
        for chunk in final_chunks:
            tokens = self.tokenizer.encode(chunk)
            if len(tokens) > self.chunk_size:
                # If a chunk is still too big, force split it by characters/tokens
                for i in range(0, len(tokens), self.chunk_size - self.chunk_overlap):
                    sub_chunk_tokens = tokens[i : i + self.chunk_size]
                    re_split_chunks.append(self.tokenizer.decode(sub_chunk_tokens))
            else:
                re_split_chunks.append(chunk)

        return re_split_chunks

    def split_document(self, document_content, filepath):
        """
        Splits a single document's content into chunks.

        Args:
            document_content (str): The full text content of the document.
            filepath (str): The original filepath of the document.

        Returns:
            list: A list of dictionaries, where each dictionary represents a chunk:
                  - 'content': The text content of the chunk.
                  - 'filepath': The original filepath of the document.
                  - 'chunk_id': A unique identifier for the chunk.
        """
        chunks = self._split_text(document_content, self.separators)
        
        # Filter out empty chunks and add metadata
        processed_chunks = []
        for i, chunk_text in enumerate(chunks):
            if chunk_text.strip(): # Ensure chunk is not just whitespace
                processed_chunks.append({
                    'content': chunk_text.strip(),
                    'filepath': filepath,
                    'chunk_id': f"{filepath}_{i}" # Simple unique ID for the chunk
                })
        return processed_chunks

# Load environment variables
dotenv.load_dotenv()

# Chunking configuration
CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', 1000))  # Max tokens per chunk
CHUNK_OVERLAP = int(os.getenv('CHUNK_OVERLAP', 200))  # Overlap between chunks

def create_workitem_chunks(cleaned_workitems):
    """
    Create chunks from cleaned work item data.
    
    Args:
        cleaned_workitems (list): List of cleaned work item dictionaries
        
    Returns:
        list: List of chunk dictionaries with content and metadata
    """
    chunks = []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""]
    )
    
    for item in cleaned_workitems:
        workitem_id = item['id']
        
        # Create main content for chunking
        content_parts = []
        
        # Always include title and basic info
        content_parts.append(f"Work Item ID: {workitem_id}")
        content_parts.append(f"Title: {item.get('title', '')}")
        content_parts.append(f"State: {item.get('state', '')}")
        
        if item.get('assigned_to'):
            content_parts.append(f"Assigned to: {item['assigned_to']}")
        
        # Add description if available
        if item.get('description'):
            content_parts.append(f"Description:\n{item['description']}")
        
        # Add comments if available
        if item.get('comments'):
            comments_text = '\n'.join(item['comments'])
            content_parts.append(f"Comments:\n{comments_text}")
        
        # Add relationship information
        if item.get('parent_work_items'):
            parent_ids = ', '.join(map(str, item['parent_work_items']))
            content_parts.append(f"Parent Work Items: {parent_ids}")
        
        if item.get('child_work_items'):
            child_ids = ', '.join(map(str, item['child_work_items']))
            content_parts.append(f"Child Work Items: {child_ids}")
        
        if item.get('related_work_items'):
            related_ids = ', '.join(map(str, item['related_work_items']))
            content_parts.append(f"Related Work Items: {related_ids}")
        
        # TODO: Add image information when image processing is implemented
        # if item.get('image_files'):
        #     image_info = ', '.join(item['image_files'])
        #     content_parts.append(f"Attached Images: {image_info}")
        
        full_content = '\n\n'.join(content_parts)
        
        # Create chunks using the text splitter
        try:
            # For work items, we'll treat each as a single document
            chunk_docs = splitter.split_document(full_content, f"workitem_{workitem_id}")
            
            # If split_document method doesn't exist, use the internal _split_text method
            if not chunk_docs:
                text_chunks = splitter._split_text(full_content, splitter.separators)
                chunk_docs = []
                for i, chunk_content in enumerate(text_chunks):
                    chunk_docs.append({
                        'content': chunk_content,
                        'filepath': f"workitem_{workitem_id}",
                        'chunk_id': f"workitem_{workitem_id}_chunk_{i}"
                    })
            
            # Process each chunk
            for i, chunk_doc in enumerate(chunk_docs):
                chunk = {
                    'chunk_id': f"workitem_{workitem_id}_chunk_{i}",
                    'content': chunk_doc.get('content', chunk_doc) if isinstance(chunk_doc, dict) else chunk_doc,
                    'workitem_id': workitem_id,
                    'metadata': {
                        'id': workitem_id,
                        'title': item.get('title', ''),
                        'state': item.get('state', ''),
                        'assigned_to': item.get('assigned_to', ''),
                        'parent_work_items': item.get('parent_work_items', []),
                        'child_work_items': item.get('child_work_items', []),
                        'related_work_items': item.get('related_work_items', []),
                        'chunk_index': i,
                        'total_chunks': len(chunk_docs),
                        'type': 'azure_devops_workitem'
                    }
                }
                chunks.append(chunk)
                
        except Exception as e:
            print(f"Warning: Failed to chunk work item {workitem_id}: {e}")
            # Fallback: create a single chunk with the full content
            chunk = {
                'chunk_id': f"workitem_{workitem_id}_chunk_0",
                'content': full_content,
                'workitem_id': workitem_id,
                'metadata': {
                    'id': workitem_id,
                    'title': item.get('title', ''),
                    'state': item.get('state', ''),
                    'assigned_to': item.get('assigned_to', ''),
                    'parent_work_items': item.get('parent_work_items', []),
                    'child_work_items': item.get('child_work_items', []),
                    'related_work_items': item.get('related_work_items', []),
                    'chunk_index': 0,
                    'total_chunks': 1,
                    'type': 'azure_devops_workitem'
                }
            }
            chunks.append(chunk)
    
    return chunks

def main():
    """Main function to chunk cleaned work item data."""
    input_file = Path("stage/cleaned_workitems.json")
    output_file = Path("stage/chunked_workitems.json")
    
    # Ensure stage directory exists
    output_file.parent.mkdir(exist_ok=True)
    
    if not input_file.exists():
        print(f"Error: Input file {input_file} not found.")
        print("Please run cleaner.py first to generate cleaned work items.")
        return
    
    print(f"Loading cleaned work items from {input_file}...")
    
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            cleaned_workitems = json.load(f)
        
        print(f"Loaded {len(cleaned_workitems)} cleaned work items.")
        
        # Create chunks
        print("Creating chunks from work items...")
        chunks = create_workitem_chunks(cleaned_workitems)
        
        # Save chunked data
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(chunks, f, indent=2, ensure_ascii=False)
        
        print(f"Chunked work items saved to {output_file}")
        print(f"Successfully created {len(chunks)} chunks from {len(cleaned_workitems)} work items.")
        
        # Display statistics
        workitem_chunk_counts = {}
        for chunk in chunks:
            workitem_id = chunk['workitem_id']
            workitem_chunk_counts[workitem_id] = workitem_chunk_counts.get(workitem_id, 0) + 1
        
        avg_chunks_per_workitem = len(chunks) / len(cleaned_workitems) if cleaned_workitems else 0
        print(f"Average chunks per work item: {avg_chunks_per_workitem:.2f}")
        
        # Display sample chunk
        if chunks:
            print(f"\nSample chunk:")
            print(f"Chunk ID: {chunks[0]['chunk_id']}")
            print(f"Work Item ID: {chunks[0]['workitem_id']}")
            print(f"Content preview: {chunks[0]['content'][:200]}...")
    
    except Exception as e:
        print(f"Error processing chunks: {e}")

if __name__ == "__main__":
    main()
