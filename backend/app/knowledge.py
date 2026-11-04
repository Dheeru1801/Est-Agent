"""Document ingestion and Pinecone-backed retrieval."""
import os
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.embeddings import Embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter


class GeminiRetrievalEmbeddings(Embeddings):
    """Use Gemini's retrieval-specific task modes with the existing Pinecone dimension."""

    def __init__(self):
        self.model = GoogleGenerativeAIEmbeddings(
            model=os.getenv("EMBEDDING_MODEL", "gemini-embedding-001"),
            google_api_key=os.environ["GOOGLE_API_KEY"],
            output_dimensionality=int(os.getenv("EMBEDDING_DIMENSION", "384")),
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.model.embed_documents(texts, task_type="RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> list[float]:
        return self.model.embed_query(text, task_type="RETRIEVAL_QUERY")


def _vector_store():
    if not os.getenv("PINECONE_API_KEY"):
        raise RuntimeError("Set PINECONE_API_KEY in backend/.env to use the vector store.")
    if not os.getenv("PINECONE_INDEX"):
        raise RuntimeError("Set PINECONE_INDEX in backend/.env to use the vector store.")
    if not os.getenv("GOOGLE_API_KEY"):
        raise RuntimeError("Set GOOGLE_API_KEY in backend/.env to use Gemini chat and embeddings.")
    embeddings = GeminiRetrievalEmbeddings()
    return PineconeVectorStore(index_name=os.environ["PINECONE_INDEX"], embedding=embeddings)


def ingest_file(path: str, filename: str) -> int:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        docs = PyPDFLoader(path).load()
    elif suffix in {".txt", ".md", ".csv", ".json"}:
        docs = TextLoader(path, encoding="utf-8", autodetect_encoding=True).load()
    else:
        raise ValueError("Supported files: PDF, TXT, Markdown, CSV, and JSON.")
    for doc in docs:
        doc.metadata["source"] = filename
    chunks = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150).split_documents(docs)
    if chunks:
        _vector_store().add_documents(chunks)
    return len(chunks)


def retrieve_context(query: str) -> str:
    try:
        docs = _vector_store().similarity_search(query, k=4)
    except Exception as exc:
        return f"Knowledge base is not ready or retrieval failed: {exc}"
    if not docs:
        return "No matching document passages were found."
    return "\n\n".join(f"[Source: {d.metadata.get('source', 'unknown')}; page: {d.metadata.get('page', 'n/a')}]\n{d.page_content}" for d in docs)
