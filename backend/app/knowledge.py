"""Document ingestion and Pinecone-backed retrieval."""
import hashlib
import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

import pymupdf
import pymupdf4llm
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import HeadingHierarchyOptions, PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docx import Document as WordDocument
from google import genai
from google.genai import types
from langchain_community.document_loaders import TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pinecone import EmbedQuery, Pinecone


CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
MARKDOWN_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
PLAIN_HEADING = re.compile(r"^[A-Z0-9][\w &'()/,:-]{0,99}$")
MIN_PDF_TEXT_CHARS_PER_PAGE = 80
TEXT_FILE_SUFFIXES = frozenset({".txt", ".md", ".csv", ".json"})
SUPPORTED_FILE_SUFFIXES = frozenset({".pdf", ".docx"}) | TEXT_FILE_SUFFIXES
SUPPORTED_FILE_TYPES = "PDF, DOCX, TXT, Markdown, CSV, JSON, or ZIP archives of supported files"
logger = logging.getLogger(__name__)


def _heading_for_line(lines: list[str], index: int) -> tuple[int, str] | None:
    """Return a heading level and title for a recognized heading line.

    Args:
        lines: All extracted document lines.
        index: Index of the candidate line.

    Returns:
        A ``(level, title)`` pair, or ``None`` when the line is ordinary text.
    """
    line = lines[index]
    markdown_heading = MARKDOWN_HEADING.match(line)
    if markdown_heading:
        return len(markdown_heading.group(1)), markdown_heading.group(2).strip()

    candidate = line.strip()
    if (
        not candidate
        or len(candidate.split()) > 12
        or candidate.endswith((".", "?", "!"))
    ):
        return None

    previous_blank = index == 0 or not lines[index - 1].strip()
    next_blank = index + 1 == len(lines) or not lines[index + 1].strip()
    title_case = candidate.istitle() or candidate.isupper()
    if previous_blank and next_blank and title_case and PLAIN_HEADING.fullmatch(candidate):
        return 2, candidate
    return None


def _heading_sections(doc: Document) -> list[tuple[list[str], str]]:
    """Parse heading-led sections from Markdown or simple extracted text.

    Markdown heading markers provide explicit hierarchy. For plain extracted
    text, only short, standalone title-like lines separated by blank lines are
    treated as headings.

    Args:
        doc: A LangChain document containing extracted source text.

    Returns:
        Heading paths paired with their section text. Returns an empty list when
        no headings are detected.
    """
    lines = doc.page_content.splitlines()
    sections: list[tuple[list[str], str]] = []
    heading_path: list[str] = []
    body: list[str] = []
    saw_heading = False

    def save_body():
        """Append the current body text under its active heading path."""
        content = "\n".join(body).strip()
        if content:
            sections.append((heading_path.copy(), content))
        body.clear()

    for index, line in enumerate(lines):
        heading = _heading_for_line(lines, index)
        if heading is None:
            body.append(line)
            continue
        level, title = heading
        saw_heading = True
        save_body()
        heading_path[:] = heading_path[: level - 1]
        heading_path.append(title)

    save_body()
    return sections if saw_heading else []


def _split_document(doc: Document) -> list[Document]:
    """Split a document by headings when present, otherwise by text boundaries.

    Small sibling sections are grouped up to ``CHUNK_SIZE``. Larger sections
    are split recursively with ``CHUNK_OVERLAP`` character overlap.

    Args:
        doc: A LangChain document containing text and source metadata.

    Returns:
        Chunk documents with inherited metadata and detected heading metadata.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        add_start_index=True,
    )
    sections = _heading_sections(doc)
    if not sections:
        return splitter.split_documents([doc])

    chunks: list[Document] = []
    group_path: list[str] = []
    group_paths: list[list[str]] = []
    group_parts: list[str] = []
    group_length = 0

    def emit_group():
        """Split and append the accumulated heading group."""
        nonlocal group_path, group_paths, group_parts, group_length
        if not group_parts:
            return
        text = "\n\n".join(group_parts).strip()
        metadata = {**doc.metadata, "section_paths": [" > ".join(path) for path in group_paths]}
        if group_path:
            metadata["heading_path"] = group_path.copy()
            metadata["title"] = group_path[0]
            subtitles = list(dict.fromkeys(
                subtitle
                for path in group_paths
                for subtitle in path[1:]
            ))
            if subtitles:
                metadata["subtitles"] = subtitles
        grouped_doc = Document(page_content=text, metadata=metadata)
        pieces = splitter.split_documents([grouped_doc])
        chunks.extend(pieces)
        group_path, group_paths, group_parts, group_length = [], [], [], 0

    for path, content in sections:
        # A new top-level heading always starts a fresh group. Subsections under
        # the same top-level heading can share a group while they fit.
        starts_new_top_level = (
            bool(group_parts) and bool(path) and len(path) == 1
            and (not group_path or path[0] != group_path[0])
        )
        part = f"{' > '.join(path)}\n{content}" if path else content
        would_exceed = group_parts and group_length + len(part) + 2 > CHUNK_SIZE
        if starts_new_top_level or would_exceed:
            emit_group()
        if not group_parts:
            group_path = path.copy()
        if path not in group_paths:
            group_paths.append(path.copy())
        group_parts.append(part)
        group_length += len(part) + 2
    emit_group()
    return chunks


def _load_pdf_with_pymupdf4llm(path: str) -> tuple[list[Document], bool, float]:
    """Extract per-page Markdown and collect parser-routing signals.

    Args:
        path: Filesystem path to the PDF.

    Returns:
        A tuple containing page documents, whether a table was detected, and
        the average extracted character count per page.
    """

    pages = pymupdf4llm.to_markdown(path, page_chunks=True)
    docs: list[Document] = []
    table_detected = False
    text_chars = 0
    page_count = len(pages)
    for index, page_data in enumerate(pages):
        text = page_data.get("text", "")
        page_meta = page_data.get("metadata") or {}
        page_number = page_meta.get("page", index + 1)
        if isinstance(page_number, int) and page_number == 0:
            page_number = 1
        text_chars += len(text.strip())
        table_detected = table_detected or bool(page_data.get("tables")) or any(
            box.get("class") == "table"
            for box in page_data.get("page_boxes", [])
            if isinstance(box, dict)
        )
        if text.strip():
            docs.append(Document(
                page_content=text,
                metadata={"page": page_number, "parser": "pymupdf4llm"},
            ))
    average_chars = text_chars / page_count if page_count else 0
    return docs, table_detected, average_chars


def _load_pdf_with_docling(path: str) -> list[Document]:
    """Convert a complex or sparse-text PDF to structured Markdown with Docling.

    Args:
        path: Filesystem path to the PDF.

    Returns:
        A document containing exported Markdown and parser metadata.

    Raises:
        ValueError: If Docling produces no text for the PDF.
    """
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = True
    pipeline_options.do_table_structure = True
    pipeline_options.heading_hierarchy_options = HeadingHierarchyOptions(enabled=True)
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )
    converted = converter.convert(path).document
    markdown = converted.export_to_markdown()
    if not markdown.strip():
        raise ValueError("Docling could not extract text from this PDF.")
    return [Document(page_content=markdown, metadata={"parser": "docling"})]


def _load_pdf(path: str) -> tuple[list[Document], str]:
    """Select PyMuPDF4LLM or Docling using text density and table detection.

    Args:
        path: Filesystem path to the PDF.

    Returns:
        The parsed source documents and the selected parser name.
    """
    docs, has_tables, average_chars = _load_pdf_with_pymupdf4llm(path)
    if average_chars < MIN_PDF_TEXT_CHARS_PER_PAGE:
        reason = "sparse_or_scanned_text"
    elif has_tables:
        reason = "tables_detected"
    else:
        return docs, "pymupdf4llm"

    docling_docs = _load_pdf_with_docling(path)
    for doc in docling_docs:
        doc.metadata["parser_reason"] = reason
    return docling_docs, "docling"


def _load_docx(path: str) -> list[Document]:
    """Extract paragraphs and tables from a Word document as Markdown text."""
    word_document = WordDocument(path)
    content: list[str] = []
    for paragraph in word_document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        heading = re.match(r"Heading\s+(\d+)", paragraph.style.name, re.IGNORECASE)
        if heading:
            level = max(1, min(int(heading.group(1)), 6))
            content.append(f"{'#' * level} {text}")
        else:
            content.append(text)
    for table in word_document.tables:
        for row in table.rows:
            values = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            content.append(" | ".join(values))
    text = "\n\n".join(content).strip()
    if not text:
        raise ValueError("No readable text was found in this DOCX file.")
    return [Document(page_content=text, metadata={"parser": "python-docx"})]


def _describe_pdf_images(path: str) -> list[Document]:
    """Create Gemini captions for selected embedded PDF figures.

    Full-page scans and small images are skipped because OCR and text extraction
    are handled by the selected PDF parser. At most the configured number of
    unique embedded images are sent to Gemini.

    Args:
        path: Filesystem path to the PDF.

    Returns:
        Caption documents with page, image, and content-type metadata.
    """
    if os.getenv("PDF_IMAGE_CAPTIONS", "true").lower() not in {"1", "true", "yes", "on"}:
        return []

    max_images = max(0, int(os.getenv("PDF_MAX_IMAGES_PER_FILE", "8")))
    if not max_images:
        return []

    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    model_name = os.getenv(
        "PDF_VISION_MODEL",
        os.getenv("CHAT_MODEL", "gemini-3.1-flash-lite"),
    )
    pdf = pymupdf.open(path)
    descriptions: list[Document] = []
    seen_xrefs: set[int] = set()
    caption_attempts = 0
    try:
        for page_index, page in enumerate(pdf):
            for image_info in page.get_image_info(xrefs=True):
                xref = image_info.get("xref", 0)
                width, height = image_info.get("width", 0), image_info.get("height", 0)
                bbox = image_info.get("bbox", (0, 0, 0, 0))
                image_area = max(0, bbox[2] - bbox[0]) * max(0, bbox[3] - bbox[1])
                page_area = max(1, page.rect.width * page.rect.height)
                if (
                    not xref or xref in seen_xrefs
                    or width < 180 or height < 120 or width * height < 50_000
                    or image_area / page_area > 0.80
                ):
                    continue
                if caption_attempts >= max_images:
                    return descriptions
                seen_xrefs.add(xref)
                caption_attempts += 1
                prompt = (
                    "Describe this meaningful figure, chart, or diagram for a "
                    "searchable document knowledge base. Include visible labels "
                    "and the main takeaway when clear. Do not guess values or facts "
                    "that are not legible. Return a concise description only."
                )
                try:
                    image = pdf.extract_image(xref)
                    image_bytes = image["image"]
                    extension = image.get("ext", "png").lower()
                    mime_type = (
                        "image/jpeg"
                        if extension in {"jpg", "jpeg"}
                        else f"image/{extension}"
                    )
                    response = client.models.generate_content(
                        model=model_name,
                        contents=[
                            prompt,
                            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                        ],
                        config=types.GenerateContentConfig(
                            max_output_tokens=192,
                            temperature=0.2,
                        ),
                    )
                    caption = (response.text or "").strip()
                    if caption:
                        descriptions.append(Document(
                            page_content=f"Figure description: {caption}",
                            metadata={
                                "page": page_index + 1,
                                "parser": "gemini_vision",
                                "content_type": "image_description",
                                "image_id": hashlib.sha256(image_bytes).hexdigest()[:16],
                            },
                        ))
                except Exception as exc:
                    # Preserve text/OCR indexing if captioning hits an API or quota error.
                    logger.warning(
                        "Could not caption a PDF image on page %s: %s",
                        page_index + 1,
                        exc,
                    )
    finally:
        pdf.close()
    return descriptions


@lru_cache(maxsize=1)
def _pinecone_index():
    """Connect to the configured Pinecone document index.

    Returns:
        A Pinecone SDK index handle for integrated document operations.

    Raises:
        RuntimeError: If a required Pinecone setting is absent.
    """
    if not os.getenv("PINECONE_API_KEY"):
        raise RuntimeError("Set PINECONE_API_KEY in backend/.env to use the vector store.")
    if not os.getenv("PINECONE_INDEX"):
        raise RuntimeError("Set PINECONE_INDEX in backend/.env to use the vector store.")
    client = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    return client.index(os.environ["PINECONE_INDEX"])


def _pinecone_namespace() -> str:
    """Return the namespace used for document records."""
    return os.getenv("PINECONE_NAMESPACE", "default")


def _record_fields(metadata: dict) -> dict:
    """Convert chunk metadata into scalar fields accepted by Pinecone records.

    Args:
        metadata: Metadata attached to a LangChain document chunk.

    Returns:
        JSON-compatible scalar fields, with heading lists made readable.
    """
    fields = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            fields[key] = value
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            fields[key] = " > ".join(value) if key in {
                "heading_path", "subtitles", "section_paths"
            } else json.dumps(value, ensure_ascii=False)
        else:
            fields[key] = json.dumps(value, ensure_ascii=False, default=str)
    return fields


def ingest_file(
    path: str,
    filename: str,
    document_id: str | None = None,
) -> tuple[int, str, int]:
    """Parse, chunk, embed, and index one supported source file.

    Args:
        path: Temporary or persistent filesystem path to the uploaded file.
        filename: Original filename, stored as the chunk source metadata.
        document_id: Stable upload ID used to avoid vector ID collisions.

    Returns:
        A tuple of indexed chunk count, selected parser name, and generated
        image-caption count.

    Raises:
        ValueError: If the file extension is not supported.
        RuntimeError: If required model or vector-store configuration is absent.
    """
    suffix = Path(filename).suffix.lower()
    image_description_count = 0
    if suffix == ".pdf":
        docs, parser = _load_pdf(path)
        image_docs = _describe_pdf_images(path)
        image_description_count = len(image_docs)
        docs.extend(image_docs)
        for doc in docs:
            doc.metadata.setdefault("parser", parser)
    elif suffix == ".docx":
        docs = _load_docx(path)
        parser = "python-docx"
    elif suffix in TEXT_FILE_SUFFIXES:
        docs = TextLoader(path, encoding="utf-8", autodetect_encoding=True).load()
        parser = "textloader"
    else:
        raise ValueError(f"Supported files: {SUPPORTED_FILE_TYPES}.")
    for doc in docs:
        doc.metadata["source"] = filename
    chunks = [
        chunk
        for doc in docs
        for chunk in _split_document(doc)
    ]
    if chunks:
        records = []
        for index, chunk in enumerate(chunks):
            content = chunk.page_content
            record_id = hashlib.sha256(
                f"{document_id or filename}\0{index}\0{content}".encode("utf-8")
            ).hexdigest()
            records.append({
                "_id": record_id,
                "chunk_text": content,
                **_record_fields(chunk.metadata),
            })
        result = _pinecone_index().documents.batch_upsert(
            namespace=_pinecone_namespace(),
            documents=records,
        )
        if result.errors:
            first_error = result.errors[0]
            raise RuntimeError(
                f"Pinecone rejected an indexing batch: {first_error.error_message}"
            )
    return len(chunks), parser, image_description_count


def retrieve_context(query: str) -> str:
    """Retrieve the four closest chunks and format them for the agent.

    Args:
        query: The user's knowledge-base question or search phrase.

    Returns:
        Retrieved passages with source and page labels, or an explanatory
        message when retrieval fails or returns no matches.
    """
    try:
        results = _pinecone_index().documents.search(
            namespace=_pinecone_namespace(),
            top_k=4,
            score_by=[EmbedQuery(field="chunk_text", query=query)],
            include_fields=[
                "chunk_text", "source", "page", "title", "subtitles",
                "parser", "content_type",
            ],
        )
    except Exception as exc:
        return f"Knowledge base is not ready or retrieval failed: {exc}"
    if not results.matches:
        return "No matching document passages were found."
    passages = [
        (
            f"[Source: {match.get('source', 'unknown')}; "
            f"page: {match.get('page', 'n/a')}]\n"
            f"{match.get('chunk_text', '')}"
        )
        for match in results.matches
    ]
    return "\n\n".join(passages)
