"""Guardrails determinísticos (independentes do LLM).

- validar_entrada: mensagem vazia/longa, ação proibida (alterar nota/registro), tentativa de prompt injection.
- intencao_explicita_de_registro: só permite a Tool de ação se o estudante pediu claramente.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


def normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


# ação proibida: alterar/mudar/aumentar/corrigir nota, frequência, falta, histórico...
_ACAO_PROIBIDA = re.compile(
    r"\b(alter\w*|mud\w*|modific\w*|aument\w*|troc\w*|edit\w*|lanc\w*|coloc\w*|atualiz\w*|apag\w*|remov\w*|"
    r"zer\w*|abon\w*)\b[^.?!]{0,40}\b(nota|notas|media|conceito|frequencia|faltas?|presenca|historico|boletim)\b"
)
_NOTA_PARA_VALOR = re.compile(r"\b(nota|media)\b[^.?!]{0,20}\bpara\s+\d+([.,]\d+)?\b")

_INJECAO = re.compile(
    r"(ignore|desconsidere|esqueca|desative|burle)\s+(as\s+|todas\s+as\s+|suas\s+|os\s+|o\s+)?"
    r"(politicas|regras|instrucoes|diretrizes|restricoes|limites|prompt|system)"
    r"|voce agora e|finja (que e|ser)|modo desenvolvedor|jailbreak|revele (o|seu) prompt"
)

_INTENCAO_REGISTRO = re.compile(
    r"\b(abr[ae]|abrir|abram|registr[ae]|registrar|cri[ae]|criar|protocol[ae]|protocolar|"
    r"solicit[ae]|faca|fazer|pode abrir|quero abrir|quero registrar|quero solicitar|gostaria de (abrir|registrar|solicitar)|"
    r"preciso (abrir|registrar|solicitar))\b"
    r"[^?]{0,80}\b(solicitacao|pedido|protocolo|chamado|ocorrencia|segunda via|requerimento|revisao|"
    r"declaracao|trancamento|cancelamento|certificado)\b"
)
_DUVIDA = re.compile(r"^(como|qual|quais|quando|onde|o que|posso|e possivel|existe|quanto)\b")


@dataclass
class ResultadoGuardrail:
    permitido: bool
    motivo: str = ""
    sinais: list[str] = field(default_factory=list)


def validar_entrada(texto: str | None, max_chars: int = 2000) -> ResultadoGuardrail:
    if texto is None or not texto.strip():
        return ResultadoGuardrail(False, "mensagem_vazia", ["mensagem_vazia"])
    if len(texto) > max_chars:
        return ResultadoGuardrail(False, "mensagem_muito_longa", ["mensagem_muito_longa"])
    t = normalizar(texto)
    sinais = []
    if _INJECAO.search(t):
        sinais.append("tentativa_prompt_injection")
    if _ACAO_PROIBIDA.search(t) or _NOTA_PARA_VALOR.search(t):
        # "como solicito revisão de nota" não casa: exige verbo de alteração ou "nota para 10"
        sinais.append("acao_proibida_alterar_registro")
        return ResultadoGuardrail(False, "acao_proibida", sinais)
    return ResultadoGuardrail(True, "", sinais)


def intencao_explicita_de_registro(texto: str) -> bool:
    """True quando o estudante pede para ABRIR/REGISTRAR algo (não apenas pergunta como funciona)."""
    t = normalizar(texto)
    if not _INTENCAO_REGISTRO.search(t):
        return False
    # "Como solicito revisão?" é dúvida de procedimento, não pedido de registro
    return not (_DUVIDA.match(t) and "?" in texto)
