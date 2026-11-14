"""Fábrica de embeddings (interface LangChain `Embeddings`).

Provedores suportados (EMBEDDING_PROVIDER):
- fastembed : local, CPU, ONNX, sem conta (padrão)
- ollama    : servidor Ollama local (ex.: nomic-embed-text)
- gemini    : Google Generative AI embeddings (ex.: models/text-embedding-004)

O mesmo provedor/modelo deve ser usado na ingestão e na consulta; o índice grava
essa informação e a consulta recusa índices incompatíveis (ver vetores.py).
"""
from __future__ import annotations

from langchain_core.embeddings import Embeddings

from .config import RAIZ, Config


class FastEmbedEmbeddings(Embeddings):
    """Wrapper mínimo do fastembed (ONNX) no contrato do LangChain."""

    def __init__(self, model_name: str):
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._modelo = TextEmbedding(model_name=model_name, cache_dir=str(RAIZ / "dados" / "cache_modelos"))
        # modelos E5 exigem prefixos assimétricos "query:" / "passage:"
        self._e5 = "e5" in model_name.lower()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._e5:
            texts = [f"passage: {t}" for t in texts]
        return [v.tolist() for v in self._modelo.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        if self._e5:
            return next(iter(self._modelo.embed([f"query: {text}"]))).tolist()
        return next(iter(self._modelo.query_embed(text))).tolist()


def criar_embeddings(cfg: Config) -> Embeddings:
    provedor = cfg.embedding_provider
    if provedor == "fastembed":
        return FastEmbedEmbeddings(cfg.embedding_model)
    if provedor == "ollama":
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(model=cfg.embedding_model, base_url=cfg.embedding_base_url or "http://localhost:11434")
    if provedor in {"gemini", "google"}:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(model=cfg.embedding_model,
                                            google_api_key=cfg.embedding_api_key or cfg.llm_api_key)
    raise ValueError(f"EMBEDDING_PROVIDER não suportado: {provedor!r} (use fastembed, ollama ou gemini)")


def identidade_embeddings(cfg: Config) -> str:
    return f"{cfg.embedding_provider}:{cfg.embedding_model}"
