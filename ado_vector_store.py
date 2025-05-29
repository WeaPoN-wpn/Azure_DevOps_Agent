# ado_vector_store.py
# Vector store implementation for Azure DevOps work item embeddings
# Provides similarity search and vector operations for the RAG system

import json
import os
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
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

class ADOVectorStore:
    """
    Vector store for Azure DevOps work item embeddings.
    Provides similarity search and vector operations for RAG system.
    """
    
    def __init__(self, embeddings_file: str = "stage/workitem_embeddings.json"):
        """
        Initialize the vector store.
        
        Args:
            embeddings_file (str): Path to the embeddings JSON file
        """
        self.embeddings_file = Path(embeddings_file)
        self.embeddings_data: List[Dict[str, Any]] = []
        self.embeddings_matrix: Optional[np.ndarray] = None
        self.chunk_metadata: List[Dict[str, Any]] = []
        
        # Initialize Azure OpenAI client for query embeddings
        self.client = AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_API_KEY,
            api_version=AZURE_OPENAI_API_VERSION
        )
        
        # Load embeddings data
        self.load_embeddings()
    
    def load_embeddings(self) -> None:
        """Load embeddings data from JSON file and prepare for similarity search."""
        if not self.embeddings_file.exists():
            print(f"Error: Embeddings file {self.embeddings_file} not found.")
            print("Please run embedding.py first to generate embeddings.")
            return
        
        try:
            print(f"Loading embeddings from {self.embeddings_file}...")
            
            with open(self.embeddings_file, 'r', encoding='utf-8') as f:
                self.embeddings_data = json.load(f)
            
            if not self.embeddings_data:
                print("Warning: No embeddings data loaded.")
                return
            
            # Extract embeddings and metadata
            embeddings_list = []
            metadata_list = []
            
            for item in self.embeddings_data:
                if 'embedding' in item and item['embedding']:
                    embeddings_list.append(item['embedding'])
                    metadata_list.append({
                        'chunk_id': item['chunk_id'],
                        'content': item['content'],
                        'workitem_id': item['workitem_id'],
                        'metadata': item.get('metadata', {})
                    })
            
            if embeddings_list:
                self.embeddings_matrix = np.array(embeddings_list, dtype=np.float32)
                self.chunk_metadata = metadata_list
                
                print(f"Loaded {len(embeddings_list)} embeddings")
                print(f"Embedding dimension: {self.embeddings_matrix.shape[1]}")
            else:
                print("Error: No valid embeddings found in the data.")
                
        except Exception as e:
            print(f"Error loading embeddings: {e}")
    
    def get_query_embedding(self, query: str) -> Optional[np.ndarray]:
        """
        Generate embedding for a query string.
        
        Args:
            query (str): Query text to embed
            
        Returns:
            Optional[np.ndarray]: Query embedding vector or None if error
        """
        # Clean query text
        query = query.replace("\n", " ").strip()
        
        if not query:
            print("Warning: Empty query provided")
            return None
        
        try:
            response = self.client.embeddings.create(
                input=[query],
                model=EMBEDDING_MODEL_DEPLOYMENT_NAME
            )
            return np.array(response.data[0].embedding, dtype=np.float32)
            
        except APIConnectionError as e:
            print(f"Connection error: {e}")
        except RateLimitError as e:
            print(f"Rate limit exceeded: {e}")
        except APIStatusError as e:
            print(f"Azure OpenAI API error: {e.status_code} - {e.response}")
        except Exception as e:
            print(f"Unexpected error during query embedding: {e}")
        
        return None
    
    def cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """
        Calculate cosine similarity between two vectors.
        
        Args:
            vec1 (np.ndarray): First vector
            vec2 (np.ndarray): Second vector
            
        Returns:
            float: Cosine similarity score
        """
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def similarity_search(
        self, 
        query: str, 
        top_k: int = 5, 
        similarity_threshold: float = 0.0,
        workitem_filter: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Perform similarity search for a query.
        
        Args:
            query (str): Search query
            top_k (int): Number of top results to return
            similarity_threshold (float): Minimum similarity score threshold
            workitem_filter (Optional[List[str]]): Filter by specific work item IDs
            
        Returns:
            List[Dict[str, Any]]: List of search results with similarity scores
        """
        if self.embeddings_matrix is None or len(self.chunk_metadata) == 0:
            print("Error: No embeddings loaded. Please check embeddings file.")
            return []
        
        # Get query embedding
        query_embedding = self.get_query_embedding(query)
        if query_embedding is None:
            print("Error: Could not generate query embedding.")
            return []
        
        # Calculate similarities
        similarities = []
        for i, chunk_embedding in enumerate(self.embeddings_matrix):
            similarity = self.cosine_similarity(query_embedding, chunk_embedding)
            
            # Apply work item filter if provided
            if workitem_filter:
                workitem_id = str(self.chunk_metadata[i]['workitem_id'])
                if workitem_id not in workitem_filter:
                    continue
            
            # Apply similarity threshold
            if similarity >= similarity_threshold:
                similarities.append({
                    'index': i,
                    'similarity': similarity,
                    'chunk_id': self.chunk_metadata[i]['chunk_id'],
                    'content': self.chunk_metadata[i]['content'],
                    'workitem_id': self.chunk_metadata[i]['workitem_id'],
                    'metadata': self.chunk_metadata[i]['metadata']
                })
        
        # Sort by similarity (descending) and return top_k
        similarities.sort(key=lambda x: x['similarity'], reverse=True)
        return similarities[:top_k]
    
    def get_similar_chunks_by_workitem(
        self, 
        workitem_id: str, 
        query: str, 
        top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Find similar chunks within a specific work item.
        
        Args:
            workitem_id (str): Work item ID to search within
            query (str): Search query
            top_k (int): Number of top results to return
            
        Returns:
            List[Dict[str, Any]]: List of similar chunks from the work item
        """
        return self.similarity_search(
            query=query,
            top_k=top_k,
            workitem_filter=[workitem_id]
        )
    
    def get_related_workitems(
        self, 
        query: str, 
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Find work items most relevant to a query.
        
        Args:
            query (str): Search query
            top_k (int): Number of work items to return
            
        Returns:
            List[Dict[str, Any]]: List of work items with aggregated similarity scores
        """
        # Get all relevant chunks
        all_results = self.similarity_search(query=query, top_k=50)
        
        # Group by work item and calculate aggregate scores
        workitem_scores = {}
        workitem_contents = {}
        
        for result in all_results:
            workitem_id = str(result['workitem_id'])
            similarity = result['similarity']
            
            if workitem_id not in workitem_scores:
                workitem_scores[workitem_id] = []
                workitem_contents[workitem_id] = []
            
            workitem_scores[workitem_id].append(similarity)
            workitem_contents[workitem_id].append({
                'chunk_id': result['chunk_id'],
                'content': result['content'],
                'similarity': similarity
            })
        
        # Calculate aggregate scores (max similarity as primary, average as secondary)
        workitem_results = []
        for workitem_id, scores in workitem_scores.items():
            max_score = max(scores)
            avg_score = sum(scores) / len(scores)
            
            workitem_results.append({
                'workitem_id': workitem_id,
                'max_similarity': max_score,
                'avg_similarity': avg_score,
                'chunk_count': len(scores),
                'relevant_chunks': workitem_contents[workitem_id]
            })
        
        # Sort by max similarity, then by average similarity
        workitem_results.sort(key=lambda x: (x['max_similarity'], x['avg_similarity']), reverse=True)
        
        return workitem_results[:top_k]
    
    def get_chunk_by_id(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a specific chunk by its ID.
        
        Args:
            chunk_id (str): The chunk ID to retrieve
            
        Returns:
            Optional[Dict[str, Any]]: Chunk data or None if not found
        """
        for chunk in self.chunk_metadata:
            if chunk['chunk_id'] == chunk_id:
                return chunk
        return None
    
    def get_workitem_chunks(self, workitem_id: str) -> List[Dict[str, Any]]:
        """
        Get all chunks for a specific work item.
        
        Args:
            workitem_id (str): Work item ID
            
        Returns:
            List[Dict[str, Any]]: List of chunks for the work item
        """
        chunks = []
        for chunk in self.chunk_metadata:
            if str(chunk['workitem_id']) == str(workitem_id):
                chunks.append(chunk)
        return chunks
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about the vector store.
        
        Returns:
            Dict[str, Any]: Statistics about embeddings and chunks
        """
        if not self.chunk_metadata:
            return {"error": "No data loaded"}
        
        # Count unique work items
        unique_workitems = set(str(chunk['workitem_id']) for chunk in self.chunk_metadata)
        
        # Calculate chunk distribution
        workitem_chunk_counts = {}
        for chunk in self.chunk_metadata:
            workitem_id = str(chunk['workitem_id'])
            workitem_chunk_counts[workitem_id] = workitem_chunk_counts.get(workitem_id, 0) + 1
        
        avg_chunks_per_workitem = len(self.chunk_metadata) / len(unique_workitems) if unique_workitems else 0
        
        return {
            'total_chunks': len(self.chunk_metadata),
            'unique_workitems': len(unique_workitems),
            'avg_chunks_per_workitem': round(avg_chunks_per_workitem, 2),
            'max_chunks_per_workitem': max(workitem_chunk_counts.values()) if workitem_chunk_counts else 0,
            'min_chunks_per_workitem': min(workitem_chunk_counts.values()) if workitem_chunk_counts else 0,
            'embedding_dimension': self.embeddings_matrix.shape[1] if self.embeddings_matrix is not None else 0
        }

def main():
    """Main function to demonstrate vector store functionality."""
    print("Initializing ADO Vector Store...")
    
    # Initialize vector store
    vector_store = ADOVectorStore()
    
    # Display statistics
    stats = vector_store.get_statistics()
    print(f"\nVector Store Statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Example queries
    example_queries = [
        "database connection error",
        "authentication failure",
        "performance optimization",
        "user interface bug",
        "deployment issue"
    ]
    
    print(f"\nTesting similarity search with example queries:")
    
    for query in example_queries:
        print(f"\n--- Query: '{query}' ---")
        results = vector_store.similarity_search(query, top_k=3)
        
        if results:
            for i, result in enumerate(results, 1):
                print(f"{i}. Work Item {result['workitem_id']} (similarity: {result['similarity']:.3f})")
                print(f"   Chunk: {result['chunk_id']}")
                print(f"   Content: {result['content'][:100]}...")
        else:
            print("   No results found.")
    
    # Example: Get related work items
    print(f"\n--- Related Work Items for 'database connection' ---")
    related = vector_store.get_related_workitems("database connection", top_k=5)
    
    for i, item in enumerate(related, 1):
        print(f"{i}. Work Item {item['workitem_id']}")
        print(f"   Max similarity: {item['max_similarity']:.3f}")
        print(f"   Relevant chunks: {item['chunk_count']}")

if __name__ == "__main__":
    main()
