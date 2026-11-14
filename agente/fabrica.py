"""Monta o agente completo a partir da configuração."""
from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from .config import Config
from .grafo import Agente
from .llm import criar_llm
from .protocolos import RepositorioProtocolos
from .tools import criar_tools
from .vetores import Recuperador


def montar_agente(cfg: Config, recuperador: Recuperador | None = None, db_protocolos: str | None = None,
                  llm=None, memoria: bool = True) -> Agente:
    recuperador = recuperador or Recuperador(cfg)
    repositorio = RepositorioProtocolos(db_protocolos or cfg.db_protocolos)
    tools = criar_tools(recuperador, repositorio)
    return Agente(cfg, llm or criar_llm(cfg), tools, checkpointer=InMemorySaver() if memoria else None)
