import os

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, HTTPException, APIRouter
from langchain.schema import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from appfrwk.config import get_config
from .models import DocumentModel, DocumentResponse
from .store import AsnyPgVector
from .store_factory import get_vector_store
from appfrwk.logging_config import get_logger

config = get_config()
log = get_logger(__name__)

# Router information
router = APIRouter(
    prefix="/RAG",
    tags=["RAG"],
    responses={404: {"description": "Not found"}},
)

try:

    CONNECTION_STRING = f"postgresql+psycopg2://myuser:mypassword@db:5432/mydatabase"

    OPENAI_API_KEY = config.OPENAI_API_KEY
    embeddings = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY)

    mode = "async"
    pgvector_store = get_vector_store(
        connection_string=CONNECTION_STRING,
        embeddings=embeddings,
        collection_name="testcollection",
        mode=mode,
    )
    retriever = pgvector_store.as_retriever()
    template = """Answer the question based only on the following context:
    {context}

    Question: {question}
    """
    prompt = ChatPromptTemplate.from_template(template)
    model = ChatOpenAI(model_name="gpt-3.5-turbo", openai_api_key=OPENAI_API_KEY)
    chain = (
            {"context": retriever, "question": RunnablePassthrough()}
            | prompt
            | model
            | StrOutputParser()
    )


except ValueError as e:
    raise HTTPException(status_code=500, detail=str(e))
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))


def add_routes(app):
    app.include_router(router)


@router.post("/add-documents/")
async def add_documents(documents: list[DocumentModel]):
    try:
        docs = [
            Document(
                page_content=doc.page_content,
                metadata=(
                    {**doc.metadata, "digest": doc.generate_digest()}
                    if doc.metadata
                    else {"digest": doc.generate_digest()}
                ),
            )
            for doc in documents
        ]
        ids = (
            await pgvector_store.aadd_documents(docs)
            if isinstance(pgvector_store, AsnyPgVector)
            else pgvector_store.add_documents(docs)
        )
        return {"message": "Documents added successfully", "ids": ids}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get-all-ids/")
async def get_all_ids():
    try:
        if isinstance(pgvector_store, AsnyPgVector):
            ids = await pgvector_store.get_all_ids()
        else:
            ids = pgvector_store.get_all_ids()

        return ids
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/get-documents-by-ids/", response_model=list[DocumentResponse])
async def get_documents_by_ids(ids: list[str]):
    try:
        if isinstance(pgvector_store, AsnyPgVector):
            existing_ids = await pgvector_store.get_all_ids()
            documents = await pgvector_store.get_documents_by_ids(ids)
        else:
            existing_ids = pgvector_store.get_all_ids()
            documents = pgvector_store.get_documents_by_ids(ids)

        if not all(id in existing_ids for id in ids):
            raise HTTPException(status_code=404, detail="One or more IDs not found")

        return documents
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/delete-documents/")
async def delete_documents(ids: list[str]):
    try:

        existing_ids = await pgvector_store.get_all_ids()
        await pgvector_store.delete(ids=ids)

        if not all(id in existing_ids for id in ids):
            raise HTTPException(status_code=404, detail="One or more IDs not found")

        return {"message": f"{len(ids)} documents deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/")
async def quick_response(msg: str):
    result = chain.invoke(msg)
    return result
