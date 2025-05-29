# ado_qa_system.py
# Azure DevOps Work Item Question-Answering System using RAG
# Combines vector search with GPT generation for intelligent work item queries

import os
import dotenv
from typing import List, Dict, Any, Optional
from openai import AzureOpenAI
from openai import APIConnectionError, RateLimitError, APIStatusError
from ado_vector_store import ADOVectorStore

# Load environment variables
dotenv.load_dotenv()

# Azure OpenAI configuration
AZURE_OPENAI_ENDPOINT = os.getenv('AZURE_OPENAI_ENDPOINT')
AZURE_OPENAI_API_KEY = os.getenv('AZURE_OPENAI_API_KEY')
AZURE_OPENAI_API_VERSION = os.getenv('AZURE_OPENAI_API_VERSION')
GPT_MODEL_DEPLOYMENT_NAME = os.getenv('GPT_MODEL_DEPLOYMENT_NAME')

class ADOQASystem:
    """
    Azure DevOps Work Item Question-Answering System using RAG.
    Combines vector search with GPT generation for intelligent work item queries.
    """
    
    def __init__(self, embeddings_file: str = "stage/workitem_embeddings.json"):
        """
        Initialize the QA system.
        
        Args:
            embeddings_file (str): Path to the embeddings JSON file
        """
        print("Initializing Azure DevOps QA System...")
        
        # Initialize vector store
        self.vector_store = ADOVectorStore(embeddings_file)
        
        # Initialize Azure OpenAI client for LLM
        self.llm_client = AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_API_KEY,
            api_version=AZURE_OPENAI_API_VERSION
        )
        
        print("QA System initialized successfully!")
    
    def answer_question(
        self, 
        query: str, 
        top_k: int = 5,
        similarity_threshold: float = 0.3,
        include_metadata: bool = True,
        temperature: float = 0.2
    ) -> Dict[str, Any]:
        """
        Answer a question about Azure DevOps work items using RAG.
        
        Args:
            query (str): User's question
            top_k (int): Number of relevant chunks to retrieve
            similarity_threshold (float): Minimum similarity score for relevance
            include_metadata (bool): Whether to include work item metadata in context
            temperature (float): GPT model temperature (0.0-1.0, lower = more focused)
            
        Returns:
            Dict[str, Any]: Answer with metadata including sources and confidence
        """
        try:
            # 1. Retrieve relevant context from vector store
            print(f"Searching for relevant work items...")
            retrieved_chunks = self.vector_store.similarity_search(
                query=query,
                top_k=top_k,
                similarity_threshold=similarity_threshold
            )
            
            if not retrieved_chunks:
                return {
                    "answer": "I couldn't find any relevant work items for your question. Please try rephrasing your query or check if the work item data has been properly indexed.",
                    "sources": [],
                    "confidence": "low",
                    "query": query
                }
            
            # 2. Build context string
            context_str = self._build_context_string(retrieved_chunks, include_metadata)
            
            # 3. Generate response
            print(f"Generating response with GPT model...")
            response = self._generate_response(query, context_str, temperature)
            
            # 4. Calculate confidence based on similarity scores
            confidence = self._calculate_confidence(retrieved_chunks)
            
            return {
                "answer": response,
                "sources": self._format_sources(retrieved_chunks),
                "confidence": confidence,
                "query": query,
                "num_sources": len(retrieved_chunks)
            }
            
        except Exception as e:
            return {
                "answer": f"An error occurred while processing your question: {e}",
                "sources": [],
                "confidence": "error",
                "query": query
            }
    
    def _build_context_string(self, chunks: List[Dict[str, Any]], include_metadata: bool = True) -> str:
        """
        Build context string from retrieved chunks.
        
        Args:
            chunks (List[Dict[str, Any]]): Retrieved chunks with similarity scores
            include_metadata (bool): Whether to include metadata
            
        Returns:
            str: Formatted context string
        """
        context_str = ""
        
        for i, chunk in enumerate(chunks):
            context_str += f"\n--- Work Item Context {i+1} (Similarity: {chunk['similarity']:.3f}) ---\n"
            context_str += f"Work Item ID: {chunk['workitem_id']}\n"
            context_str += f"Chunk ID: {chunk['chunk_id']}\n"
            
            if include_metadata and chunk.get('metadata'):
                metadata = chunk['metadata']
                if metadata.get('title'):
                    context_str += f"Title: {metadata['title']}\n"
                if metadata.get('state'):
                    context_str += f"State: {metadata['state']}\n"
                if metadata.get('type'):
                    context_str += f"Type: {metadata['type']}\n"
                if metadata.get('assigned_to'):
                    context_str += f"Assigned To: {metadata['assigned_to']}\n"
                if metadata.get('priority'):
                    context_str += f"Priority: {metadata['priority']}\n"
                if metadata.get('area_path'):
                    context_str += f"Area Path: {metadata['area_path']}\n"
            
            context_str += f"Content:\n{chunk['content']}\n"
            context_str += "---" * 20 + "\n"
        
        return context_str
    
    def _generate_response(self, query: str, context: str, temperature: float = 0.2) -> str:
        """
        Generate response using GPT model.
        
        Args:
            query (str): User's question
            context (str): Retrieved context
            temperature (float): Model temperature
            
        Returns:
            str: Generated response
        """
        system_message = (
            "You are an expert Azure DevOps assistant specializing in work item analysis and project management. "
            "Your task is to answer questions about Azure DevOps work items based on the provided context. "
            "\nGuidelines:\n"
            "- Use ONLY the information provided in the 'Context' section to formulate your answer\n"
            "- If the information is not available in the context, clearly state that you don't know\n"
            "- Provide clear, concise, and actionable answers\n"
            "- Reference specific work item IDs when relevant\n"
            "- Include work item states, assignees, types, and priorities when helpful\n"
            "- If asked about status or progress, summarize based on work item states\n"
            "- For troubleshooting questions, focus on error descriptions and solutions mentioned\n"
            "- Organize your response with clear structure (bullet points, numbered lists when appropriate)\n"
            "- If multiple work items are relevant, group or categorize them logically\n"
            "- Always maintain a professional and helpful tone\n"
            "- When citing work items, format them as 'Work Item #[ID]' for clarity"
        )
        
        user_message = f"Context:\n{context}\n\nUser Question: {query}\n\nAnswer:"
        
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message}
        ]
        
        try:
            response = self.llm_client.chat.completions.create(
                model=GPT_MODEL_DEPLOYMENT_NAME,
                messages=messages,
                temperature=temperature,
                max_tokens=1500,
                top_p=0.9
            )
            return response.choices[0].message.content
            
        except APIConnectionError as e:
            return f"Connection error to GPT model: {e}. Check your endpoint and network."
        except RateLimitError as e:
            return f"Rate limit exceeded for GPT model: {e}. Please wait and try again."
        except APIStatusError as e:
            return f"Azure OpenAI GPT API error: {e.status_code} - {e.response}. Check your model deployment name."
        except Exception as e:
            return f"An unexpected error occurred during response generation: {e}"
    
    def _calculate_confidence(self, chunks: List[Dict[str, Any]]) -> str:
        """
        Calculate confidence level based on similarity scores.
        
        Args:
            chunks (List[Dict[str, Any]]): Retrieved chunks with similarity scores
            
        Returns:
            str: Confidence level (high, medium, low)
        """
        if not chunks:
            return "low"
        
        max_similarity = max(chunk['similarity'] for chunk in chunks)
        avg_similarity = sum(chunk['similarity'] for chunk in chunks) / len(chunks)
        
        if max_similarity >= 0.8 and avg_similarity >= 0.6:
            return "high"
        elif max_similarity >= 0.6 and avg_similarity >= 0.4:
            return "medium"
        else:
            return "low"
    
    def _format_sources(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Format source information for the response.
        
        Args:
            chunks (List[Dict[str, Any]]): Retrieved chunks
            
        Returns:
            List[Dict[str, Any]]: Formatted source information
        """
        sources = []
        for chunk in chunks:
            source = {
                "workitem_id": chunk['workitem_id'],
                "chunk_id": chunk['chunk_id'],
                "similarity": round(chunk['similarity'], 3),
                "content_preview": chunk['content'][:200] + "..." if len(chunk['content']) > 200 else chunk['content']
            }
            
            # Add metadata if available
            if chunk.get('metadata'):
                metadata = chunk['metadata']
                source.update({
                    "title": metadata.get('title', 'N/A'),
                    "state": metadata.get('state', 'N/A'),
                    "type": metadata.get('type', 'N/A'),
                    "assigned_to": metadata.get('assigned_to', 'N/A')
                })
            
            sources.append(source)
        
        return sources
    
    def get_workitem_summary(self, workitem_id: str) -> Dict[str, Any]:
        """
        Get a comprehensive summary of a specific work item.
        
        Args:
            workitem_id (str): Work item ID
            
        Returns:
            Dict[str, Any]: Summary of the work item
        """
        chunks = self.vector_store.get_workitem_chunks(workitem_id)
        
        if not chunks:
            return {
                "answer": f"Work item {workitem_id} not found in the knowledge base.",
                "workitem_id": workitem_id,
                "found": False
            }
        
        # Combine all chunks for the work item
        combined_content = ""
        metadata = chunks[0].get('metadata', {}) if chunks else {}
        
        for chunk in chunks:
            combined_content += chunk['content'] + "\n\n"
        
        context = f"Work Item ID: {workitem_id}\n"
        if metadata:
            if metadata.get('title'):
                context += f"Title: {metadata['title']}\n"
            if metadata.get('state'):
                context += f"State: {metadata['state']}\n"
            if metadata.get('type'):
                context += f"Type: {metadata['type']}\n"
            if metadata.get('assigned_to'):
                context += f"Assigned To: {metadata['assigned_to']}\n"
            if metadata.get('priority'):
                context += f"Priority: {metadata['priority']}\n"
        
        context += f"\nFull Content:\n{combined_content}"
        
        query = f"Please provide a comprehensive summary of work item {workitem_id}"
        summary = self._generate_response(query, context)
        
        return {
            "answer": summary,
            "workitem_id": workitem_id,
            "found": True,
            "metadata": metadata,
            "chunk_count": len(chunks)
        }
    
    def search_workitems_by_criteria(
        self, 
        criteria: str, 
        top_k: int = 10,
        group_by_workitem: bool = True,
        similarity_threshold: float = 0.3
    ) -> Dict[str, Any]:
        """
        Search work items by specific criteria and return organized results.
        
        Args:
            criteria (str): Search criteria or query
            top_k (int): Number of results to return
            group_by_workitem (bool): Whether to group results by work item
            similarity_threshold (float): Minimum similarity threshold
            
        Returns:
            Dict[str, Any]: Organized search results
        """
        if group_by_workitem:
            related_workitems = self.vector_store.get_related_workitems(criteria, top_k)
            
            if not related_workitems:
                return {
                    "answer": f"No work items found matching criteria: '{criteria}'",
                    "criteria": criteria,
                    "workitems": [],
                    "found": False
                }
            
            context = f"Search Results for: '{criteria}'\n\n"
            for i, item in enumerate(related_workitems, 1):
                context += f"{i}. Work Item {item['workitem_id']}\n"
                context += f"   Max Similarity: {item['max_similarity']:.3f}\n"
                context += f"   Relevant Chunks: {item['chunk_count']}\n"
                
                # Include top chunk content
                if item['relevant_chunks']:
                    top_chunk = item['relevant_chunks'][0]
                    context += f"   Content Preview: {top_chunk['content'][:200]}...\n"
                context += "\n"
            
            query = f"Summarize and organize these work items related to: {criteria}"
            summary = self._generate_response(query, context)
            
            return {
                "answer": summary,
                "criteria": criteria,
                "workitems": related_workitems,
                "found": True,
                "count": len(related_workitems)
            }
        else:
            chunks = self.vector_store.similarity_search(criteria, top_k, similarity_threshold)
            context = self._build_context_string(chunks)
            query = f"Organize and summarize these work item chunks related to: {criteria}"
            summary = self._generate_response(query, context)
            
            return {
                "answer": summary,
                "criteria": criteria,
                "chunks": chunks,
                "found": len(chunks) > 0,
                "count": len(chunks)
            }
    
    def get_system_stats(self) -> Dict[str, Any]:
        """Get statistics about the QA system."""
        vector_stats = self.vector_store.get_statistics()
        
        return {
            **vector_stats,
            "gpt_model": GPT_MODEL_DEPLOYMENT_NAME,
            "system_status": "operational" if "error" not in vector_stats else "error"
        }
    
    def batch_answer_questions(self, questions: List[str]) -> List[Dict[str, Any]]:
        """
        Answer multiple questions in batch.
        
        Args:
            questions (List[str]): List of questions to answer
            
        Returns:
            List[Dict[str, Any]]: List of answers with metadata
        """
        results = []
        for question in questions:
            print(f"Processing question: {question[:50]}...")
            result = self.answer_question(question)
            results.append(result)
        
        return results

def main():
    """Main function to demonstrate QA system functionality."""
    print("Azure DevOps QA System Demo")
    print("=" * 50)
    
    # Initialize QA system
    qa_system = ADOQASystem()
    
    # Display system statistics
    stats = qa_system.get_system_stats()
    print(f"\nSystem Statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Example questions
    example_questions = [
        "What are the current database issues?",
        "Show me all high priority bugs",
        "What tasks are assigned to the Finance Hub team?",
        "Are there any authentication problems?",
        "What's the status of deployment related work items?",
        "Which work items are in New or Active state?",
        "What are the recent completed tasks?"
    ]
    
    print(f"\n" + "=" * 50)
    print("Example Q&A Session:")
    print("=" * 50)
    
    for question in example_questions:
        print(f"\n🤔 Question: {question}")
        print("-" * 60)
        
        result = qa_system.answer_question(question, top_k=3)
        print(f"🤖 Answer: {result['answer']}")
        print(f"📊 Confidence: {result['confidence']}")
        print(f"📚 Sources: {result['num_sources']} work item chunks")
        
        print("\n" + "=" * 60)
    
    # Example: Work item summary
    print(f"\n🔍 Work Item Summary Example:")
    print("-" * 60)
    
    # Get a sample work item ID from the system
    stats = qa_system.get_system_stats()
    if stats.get('unique_workitems', 0) > 0:
        # Try to get a work item summary
        sample_chunks = qa_system.vector_store.chunk_metadata[:1]  # Get first chunk
        if sample_chunks:
            sample_workitem_id = str(sample_chunks[0]['workitem_id'])
            print(f"Getting summary for Work Item {sample_workitem_id}...")
            
            summary_result = qa_system.get_workitem_summary(sample_workitem_id)
            print(f"📋 Summary: {summary_result['answer'][:300]}...")
    
    # Example: Search by criteria
    print(f"\n🔍 Search by Criteria Example:")
    print("-" * 60)
    
    search_result = qa_system.search_workitems_by_criteria("Finance Hub", top_k=5)
    print(f"🔍 Search Results: {search_result['answer'][:300]}...")

if __name__ == "__main__":
    main()
