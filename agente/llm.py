"""Fábrica de LLMs com provedor configurável e tratamento de 429/timeout.

LLM_PROVIDER suportados:
- ollama      : modelo local via Ollama (ex.: qwen2.5:7b, llama3.1:8b)
- groq        : GroqCloud (ex.: llama-3.3-70b-versatile)
- gemini      : Google AI Studio (ex.: gemini-2.5-flash)
- openrouter  : OpenRouter (ex.: meta-llama/llama-3.3-70b-instruct:free)
- openai      : OpenAI ou qualquer endpoint compatível (LocalAI, LM Studio...) via LLM_BASE_URL
"""
from __future__ import annotations

import random
import time
from typing import Any, Callable

from langchain_core.language_models.chat_models import BaseChatModel

from .config import Config


class ErroServicoLLM(RuntimeError):
    def __init__(self, tipo: str, detalhe: str, tentativas: int):
        super().__init__(f"{tipo}: {detalhe}")
        self.tipo = tipo
        self.detalhe = detalhe
        self.tentativas = tentativas


def criar_llm(cfg: Config) -> BaseChatModel:
    p, m, t = cfg.llm_provider, cfg.llm_model, cfg.llm_temperature
    # max_retries=0 nos clientes: o retry é feito por `invocar_com_retry`, para ficar registrado no trace.
    if p == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=m, temperature=t, base_url=cfg.llm_base_url or "http://localhost:11434",
                          num_ctx=cfg.llm_num_ctx, client_kwargs={"timeout": cfg.llm_timeout_s})
    if p == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(model=m, temperature=t, api_key=cfg.llm_api_key, timeout=cfg.llm_timeout_s, max_retries=0)
    if p in {"gemini", "google"}:
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=m, temperature=t, google_api_key=cfg.llm_api_key,
                                      timeout=cfg.llm_timeout_s, max_retries=0)
    if p in {"openrouter", "openai"}:
        from langchain_openai import ChatOpenAI

        base = cfg.llm_base_url or ("https://openrouter.ai/api/v1" if p == "openrouter" else None)
        return ChatOpenAI(model=m, temperature=t, api_key=cfg.llm_api_key or "nao-usado", base_url=base,
                          timeout=cfg.llm_timeout_s, max_retries=0)
    raise ValueError(f"LLM_PROVIDER não suportado: {p!r}")


def classificar_erro(e: BaseException) -> tuple[str, bool]:
    """Retorna (tipo, pode_tentar_novamente)."""
    nome = type(e).__name__.lower()
    texto = str(e).lower()
    status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
    if status == 429 or "429" in texto or "ratelimit" in nome or "rate limit" in texto \
            or "resource_exhausted" in texto or "resourceexhausted" in nome or "quota" in texto:
        return "rate_limit_429", True
    if isinstance(e, TimeoutError) or "timeout" in nome or "timed out" in texto or "timeout" in texto:
        return "timeout", True
    # classifica pelo TIPO da exceção (e pela cadeia de causas), não só pelo texto: no Windows em português
    # a mensagem é "[WinError 10061] Nenhuma conexão pôde ser feita..."
    cadeia, atual = [], e
    while atual is not None and len(cadeia) < 5:
        cadeia.append(atual)
        atual = atual.__cause__ or atual.__context__
    if any(isinstance(x, ConnectionError) or "connect" in type(x).__name__.lower() for x in cadeia) \
            or status in {500, 502, 503, 504} or "unavailable" in texto or "10061" in texto:
        return "servico_indisponivel", True
    if status in {401, 403} or "auth" in nome or "api key" in texto or "permission" in texto:
        return "autenticacao", False
    return "erro_desconhecido", False


def invocar_com_retry(fn: Callable[[], Any], cfg: Config, tracer=None, etapa: str = "llm",
                      dormir: Callable[[float], None] = time.sleep) -> Any:
    """Executa `fn` com backoff exponencial + jitter para erros transitórios (429, timeout, 5xx)."""
    tentativas = max(1, cfg.llm_max_retries + 1)
    for n in range(1, tentativas + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            tipo, transitorio = classificar_erro(e)
            ultimo = n == tentativas or not transitorio
            espera = 0.0 if ultimo else min(30.0, (2 ** (n - 1)) * 1.5 + random.uniform(0, 0.5))
            if tracer:
                tracer.evento("erro_servico", etapa=etapa, tipo=tipo, tentativa=n, de=tentativas,
                              transitorio=transitorio, espera_s=round(espera, 2),
                              detalhe=str(e)[:200])
            if ultimo:
                raise ErroServicoLLM(tipo, str(e)[:200], n) from e
            dormir(espera)
