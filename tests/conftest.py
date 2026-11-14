"""Dublês de teste: LLM roteirizado e recuperador fixo (sem rede, sem cota)."""
from __future__ import annotations

from dataclasses import replace

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from agente.config import carregar_config
from agente.grafo import Agente
from agente.observabilidade import TracerNulo
from agente.protocolos import RepositorioProtocolos
from agente.tools import criar_tools


class Erro429(Exception):
    status_code = 429


class LLMRoteirizado:
    """Imita a interface usada pelo grafo: bind_tools / invoke / with_structured_output."""

    def __init__(self, respostas, estruturado=None):
        self.respostas = list(respostas)   # AIMessage, Exception ou callable(contexto)
        self.estruturado = estruturado      # dict {"parsed":..., "parsing_error":...} ou Exception
        self.chamadas = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, contexto):
        self.chamadas += 1
        item = self.respostas.pop(0) if len(self.respostas) > 1 else self.respostas[0]
        if isinstance(item, Exception):
            raise item
        msg = item(contexto) if callable(item) else item
        # como um LLM real: cada resposta é uma mensagem nova (id único)
        return msg.model_copy(update={"id": f"fake-{self.chamadas}"})

    def with_structured_output(self, schema, include_raw=False):
        pai = self

        class _R:
            def invoke(self, prompt):
                if isinstance(pai.estruturado, Exception):
                    raise pai.estruturado
                return pai.estruturado or {"parsed": None, "parsing_error": ValueError("sem roteiro"), "raw": None}

        return _R()


class RecuperadorFixo:
    def __init__(self, evidencias=None):
        self.evidencias = evidencias if evidencias is not None else [
            {"fonte": "ACAD-001", "titulo": "Declaração de matrícula", "categoria": "documentos", "score": 0.72,
             "trecho": "O prazo é de até 3 dias úteis."}]
        self.consultas = []

    def buscar(self, consulta, top_k=None):
        self.consultas.append(consulta)
        return self.evidencias, 0


def chamada_tool(nome, args, cid="c1"):
    return AIMessage(content="", tool_calls=[{"name": nome, "args": args, "id": cid, "type": "tool_call"}])


@pytest.fixture
def cfg(tmp_path):
    return replace(carregar_config(), max_rodadas=3, llm_max_retries=2, structured_output_mode="llm",
                   db_protocolos=str(tmp_path / "p.db"), log_dir=str(tmp_path / "logs"))


@pytest.fixture
def montar(cfg):
    def _montar(llm, recuperador=None, **overrides):
        c = replace(cfg, **overrides)
        repo = RepositorioProtocolos(c.db_protocolos)
        tools = criar_tools(recuperador or RecuperadorFixo(), repo)
        return Agente(c, llm, tools, checkpointer=InMemorySaver()), repo
    return _montar


@pytest.fixture
def tracer():
    return TracerNulo()
