"""Banco vetorial (Qdrant): ingestão e busca por similaridade com Top-K configurável.

- Sem QDRANT_URL: Qdrant *embedded* em disco (QDRANT_PATH), sem servidor nem Docker.
- Com QDRANT_URL: Qdrant em servidor local (Docker) ou Qdrant Cloud (QDRANT_API_KEY).

Cada ponto guarda em payload: fonte (ID ACAD), título, categoria, conteúdo e a
identidade do modelo de embeddings usado na ingestão (compatibilidade).
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from .config import Config
from .embeddings import criar_embeddings, identidade_embeddings


class IndiceIncompativel(RuntimeError):
    """O índice foi criado com outro modelo/dimensão de embeddings."""


def criar_cliente(cfg: Config) -> QdrantClient:
    if cfg.qdrant_url:
        return QdrantClient(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key or None, timeout=30)
    Path(cfg.qdrant_path).mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=cfg.qdrant_path)


def carregar_documentos(caminho: str) -> list[dict]:
    with open(caminho, encoding="utf-8") as f:
        docs = json.load(f)
    obrigatorios = {"id", "titulo", "categoria", "fonte", "conteudo"}
    for d in docs:
        faltando = obrigatorios - d.keys()
        if faltando:
            raise ValueError(f"documento {d.get('id')} sem campos {faltando}")
    return docs


def indexar(cfg: Config, docs: list[dict], embeddings: Embeddings | None = None,
            cliente: QdrantClient | None = None) -> tuple[dict, QdrantClient]:
    """Recria a coleção e indexa os documentos. Retorna (resumo, cliente em uso)."""
    embeddings = embeddings or criar_embeddings(cfg)
    cliente_proprio = cliente is None
    cliente = cliente or criar_cliente(cfg)
    textos = [f"{d['titulo']}. {d['conteudo']}" for d in docs]
    vetores = embeddings.embed_documents(textos)
    dim = len(vetores[0])

    if cliente.collection_exists(cfg.qdrant_collection):
        cliente.delete_collection(cfg.qdrant_collection)
        if cliente_proprio and not cfg.qdrant_url:
            # Qdrant embedded mantém o storage antigo após delete; reabrir o cliente garante coleção limpa
            # (necessário ao trocar de modelo de embeddings e, portanto, de dimensão).
            cliente.close()
            arq = Path(cfg.qdrant_path) / "collection" / cfg.qdrant_collection / "storage.sqlite"
            if arq.exists():
                arq.unlink()
            cliente = criar_cliente(cfg)
    cliente.create_collection(
        collection_name=cfg.qdrant_collection,
        vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
    )
    ident = identidade_embeddings(cfg)
    pontos = [
        qm.PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, d["id"])),
            vector=v,
            payload={
                "fonte": d["fonte"],
                "doc_id": d["id"],
                "titulo": d["titulo"],
                "categoria": d["categoria"],
                "conteudo": d["conteudo"],
                "instituicao": d.get("instituicao", ""),
                "embedding_id": ident,
            },
        )
        for d, v in zip(docs, vetores)
    ]
    cliente.upsert(collection_name=cfg.qdrant_collection, points=pontos, wait=True)
    total = cliente.count(cfg.qdrant_collection, exact=True).count
    return {"colecao": cfg.qdrant_collection, "documentos": total, "dimensao": dim, "embedding_id": ident,
            "fontes": [d["fonte"] for d in docs]}, cliente


class Recuperador:
    """Busca por similaridade (cosseno) com Top-K e limiar mínimo de score."""

    def __init__(self, cfg: Config, embeddings: Embeddings | None = None, cliente: QdrantClient | None = None):
        self.cfg = cfg
        self.embeddings = embeddings or criar_embeddings(cfg)
        self.cliente = cliente or criar_cliente(cfg)
        self.ident = identidade_embeddings(cfg)
        self._verificar_compatibilidade()

    def _verificar_compatibilidade(self) -> None:
        if not self.cliente.collection_exists(self.cfg.qdrant_collection):
            raise IndiceIncompativel(
                f"coleção '{self.cfg.qdrant_collection}' não existe. Rode: python -m agente.indexar"
            )
        info = self.cliente.get_collection(self.cfg.qdrant_collection)
        dim_indice = info.config.params.vectors.size
        dim_consulta = len(self.embeddings.embed_query("teste de compatibilidade"))
        if dim_indice != dim_consulta:
            raise IndiceIncompativel(
                f"dimensão do índice ({dim_indice}) difere do modelo de consulta ({dim_consulta}). Reindexe."
            )
        amostra, _ = self.cliente.scroll(self.cfg.qdrant_collection, limit=1, with_payload=True)
        if amostra and amostra[0].payload.get("embedding_id") != self.ident:
            raise IndiceIncompativel(
                f"índice criado com '{amostra[0].payload.get('embedding_id')}', consulta usa '{self.ident}'. Reindexe."
            )

    def buscar(self, consulta: str, top_k: int | None = None) -> tuple[list[dict], int]:
        """Retorna (evidências acima do limiar, quantidade descartada abaixo do limiar)."""
        k = top_k or self.cfg.rag_top_k
        vetor = self.embeddings.embed_query(consulta)
        pontos = self.cliente.query_points(
            collection_name=self.cfg.qdrant_collection, query=vetor, limit=k, with_payload=True
        ).points
        aceitas, descartadas = [], 0
        for p in pontos:
            if p.score < self.cfg.rag_score_min:
                descartadas += 1
                continue
            aceitas.append({
                "fonte": p.payload["fonte"],
                "titulo": p.payload["titulo"],
                "categoria": p.payload["categoria"],
                "score": round(float(p.score), 4),
                "trecho": p.payload["conteudo"],
            })
        return aceitas, descartadas
