"""Observabilidade: trace estruturado (JSONL) com mascaramento de dados sensíveis.

Cada execução do agente recebe um `trace_id`. Os eventos (decisões, Tools,
argumentos, resultados, erros e término) são gravados em
`evidencias/logs/trace_AAAAMMDD.jsonl`. Chaves de API, tokens e senhas
nunca são gravados: tudo passa por `mascarar()` antes de ir para o arquivo.
"""
from __future__ import annotations

import json
import re
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_PADROES_SENSIVEIS = [
    # chaves de API conhecidas (Groq, OpenAI/OpenRouter, Google, Pinecone, Bearer...)
    (re.compile(r"\bgsk_[A-Za-z0-9]{10,}"), "gsk_***"),
    (re.compile(r"\bsk-[A-Za-z0-9\-_]{10,}"), "sk-***"),
    (re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}"), "AIza***"),
    (re.compile(r"\bpcsk_[A-Za-z0-9_]{10,}"), "pcsk_***"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_.=]{10,}"), "Bearer ***"),
    # "senha: xyz", "token=abc", "api_key: ..."
    (re.compile(r"(?i)\b(senha|password|token|api[_-]?key|chave)\b(\s*(?:é|:|=)\s*)(\S+)"), r"\1\2***"),
    # CPF
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "***.***.***-**"),
]

_CAMPOS_SENSIVEIS = {"api_key", "llm_api_key", "qdrant_api_key", "embedding_api_key", "senha", "token", "password"}


def mascarar(valor: Any) -> Any:
    """Mascara recursivamente segredos em strings, dicts e listas."""
    if isinstance(valor, str):
        for padrao, subst in _PADROES_SENSIVEIS:
            valor = padrao.sub(subst, valor)
        return valor
    if isinstance(valor, dict):
        return {
            k: ("***" if str(k).lower() in _CAMPOS_SENSIVEIS else mascarar(v)) for k, v in valor.items()
        }
    if isinstance(valor, (list, tuple)):
        return [mascarar(v) for v in valor]
    return valor


class Tracer:
    """Grava eventos JSONL de uma execução (thread-safe, um arquivo por dia)."""

    _lock = threading.Lock()

    def __init__(self, log_dir: str, console: bool = False, trace_id: str | None = None, rotulo: str = ""):
        self.trace_id = trace_id or uuid.uuid4().hex[:12]
        self.rotulo = rotulo
        self.console = console
        self.eventos: list[dict] = []
        self._dir = Path(log_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self.arquivo = self._dir / f"trace_{datetime.now():%Y%m%d}.jsonl"

    def evento(self, tipo: str, /, **dados: Any) -> dict:
        registro = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "trace_id": self.trace_id,
            "rotulo": self.rotulo,
            "evento": tipo,
            **mascarar(dados),
        }
        self.eventos.append(registro)
        linha = json.dumps(registro, ensure_ascii=False, default=str)
        with self._lock:
            with self.arquivo.open("a", encoding="utf-8") as f:
                f.write(linha + "\n")
        if self.console:
            print(f"  [trace] {tipo}: {json.dumps(mascarar(dados), ensure_ascii=False, default=str)[:300]}",
                  file=sys.stderr)
        return registro


class TracerNulo(Tracer):
    """Tracer que não grava em disco (útil em testes unitários)."""

    def __init__(self):  # noqa: D401 - sem diretório
        self.trace_id = "nulo"
        self.rotulo = ""
        self.console = False
        self.eventos = []

    def evento(self, tipo: str, /, **dados: Any) -> dict:
        registro = {"evento": tipo, **mascarar(dados)}
        self.eventos.append(registro)
        return registro
