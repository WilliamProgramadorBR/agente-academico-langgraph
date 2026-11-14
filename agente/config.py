"""Configuração central do agente, lida do arquivo .env / variáveis de ambiente.

Nenhum valor sensível (chaves, tokens) é impresso ou registrado em log: use
`Config.resumo_seguro()` para exibir a configuração.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")


def _env(nome: str, padrao: str = "") -> str:
    """Variável vazia no .env (ex.: `QDRANT_PATH=`) é tratada como não definida."""
    return (os.getenv(nome) or "").strip() or padrao


def _env_int(nome: str, padrao: int) -> int:
    try:
        return int(_env(nome, str(padrao)))
    except ValueError:
        return padrao


def _env_float(nome: str, padrao: float) -> float:
    try:
        return float(_env(nome, str(padrao)))
    except ValueError:
        return padrao


def _env_bool(nome: str, padrao: bool) -> bool:
    return _env(nome, str(padrao)).lower() in {"1", "true", "sim", "yes", "on"}


@dataclass
class Config:
    # --- LLM (provedor configurável) ---
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "ollama").lower())
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "qwen2.5:7b"))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY"))
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL"))
    llm_temperature: float = field(default_factory=lambda: _env_float("LLM_TEMPERATURE", 0.0))
    llm_timeout_s: float = field(default_factory=lambda: _env_float("LLM_TIMEOUT_S", 120.0))
    llm_max_retries: int = field(default_factory=lambda: _env_int("LLM_MAX_RETRIES", 3))
    # Janela de contexto pedida ao Ollama. Sem isso o Ollama usa o máximo do modelo (ex.: 131072 no llama3.2),
    # alocando dezenas de GB de cache KV — observado: 17 GB, 58% na RAM. Nossos prompts têm < 3 mil tokens.
    llm_num_ctx: int = field(default_factory=lambda: _env_int("LLM_NUM_CTX", 8192))
    structured_output_mode: str = field(
        default_factory=lambda: _env("STRUCTURED_OUTPUT_MODE", "llm").lower()
    )  # "llm" (with_structured_output + fallback) ou "deterministico"

    # --- Embeddings (configuráveis; devem ser os mesmos na ingestão e na consulta) ---
    embedding_provider: str = field(default_factory=lambda: _env("EMBEDDING_PROVIDER", "ollama").lower())
    embedding_model: str = field(
        default_factory=lambda: _env(
            "EMBEDDING_MODEL", "bge-m3"
        )
    )
    embedding_api_key: str = field(default_factory=lambda: _env("EMBEDDING_API_KEY"))
    embedding_base_url: str = field(default_factory=lambda: _env("EMBEDDING_BASE_URL"))

    # --- Vector store (Qdrant embedded local, servidor local ou Qdrant Cloud) ---
    qdrant_path: str = field(default_factory=lambda: _env("QDRANT_PATH", str(RAIZ / "dados" / "qdrant")))
    qdrant_url: str = field(default_factory=lambda: _env("QDRANT_URL"))
    qdrant_api_key: str = field(default_factory=lambda: _env("QDRANT_API_KEY"))
    qdrant_collection: str = field(default_factory=lambda: _env("QDRANT_COLLECTION", "normas_academicas"))

    # --- RAG ---
    rag_top_k: int = field(default_factory=lambda: _env_int("RAG_TOP_K", 3))
    rag_score_min: float = field(default_factory=lambda: _env_float("RAG_SCORE_MIN", 0.45))

    # --- Grafo / segurança ---
    max_rodadas: int = field(default_factory=lambda: _env_int("MAX_RODADAS", 4))
    max_chars_entrada: int = field(default_factory=lambda: _env_int("MAX_CHARS_ENTRADA", 2000))

    # --- Persistência e logs ---
    base_conhecimento: str = field(
        default_factory=lambda: _env("BASE_CONHECIMENTO", str(RAIZ / "dados" / "base_conhecimento_academica.json"))
    )
    db_protocolos: str = field(default_factory=lambda: _env("DB_PROTOCOLOS", str(RAIZ / "dados" / "protocolos.db")))
    log_dir: str = field(default_factory=lambda: _env("LOG_DIR", str(RAIZ / "evidencias" / "logs")))
    log_console: bool = field(default_factory=lambda: _env_bool("LOG_CONSOLE", False))

    def resumo_seguro(self) -> dict:
        """Configuração sem segredos (apenas indica se a chave existe)."""
        return {
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "llm_base_url": self.llm_base_url or "(padrão do provedor)",
            "llm_api_key": "configurada" if self.llm_api_key else "não configurada",
            "llm_num_ctx": self.llm_num_ctx,
            "structured_output_mode": self.structured_output_mode,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "vector_store": f"qdrant ({'remoto: ' + self.qdrant_url if self.qdrant_url else 'embedded local'})",
            "qdrant_collection": self.qdrant_collection,
            "rag_top_k": self.rag_top_k,
            "rag_score_min": self.rag_score_min,
            "max_rodadas": self.max_rodadas,
        }


def carregar_config() -> Config:
    return Config()
