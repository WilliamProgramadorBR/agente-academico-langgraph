"""Contratos tipados (Pydantic) do agente: argumentos das Tools, resultados das
Tools e a resposta estruturada final."""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

PADRAO_FONTE = re.compile(r"^ACAD-\d{3}$")
PADRAO_PROTOCOLO = re.compile(r"^SOL-\d{4,6}$")

StatusResposta = Literal[
    "respondido",              # resposta baseada em fonte recuperada
    "sem_evidencia",           # abstenção: não há evidência na base
    "protocolo_consultado",    # status obtido via consultar_protocolo
    "protocolo_nao_encontrado",
    "solicitacao_registrada",  # registrar_solicitacao persistiu um protocolo
    "aguardando_dados",        # faltam dados para executar a ação
    "recusado",                # ação proibida / fora da autoridade do agente
    "erro",                    # falha de serviço, entrada inválida ou limite atingido
]

TipoSolicitacao = Literal[
    "declaracao_matricula",
    "segunda_via_certificado",
    "emissao_certificado",
    "revisao_nota",
    "trancamento",
    "cancelamento",
    "suporte_plataforma",
    "biblioteca_digital",
    "financeiro",
    "ouvidoria",
    "outro",
]

# Tipos que, pelas normas (ACAD-005, ACAD-003...), exigem dados adicionais.
CAMPOS_OBRIGATORIOS_POR_TIPO: dict[str, tuple[str, ...]] = {
    "segunda_via_certificado": ("turma", "justificativa"),   # ACAD-005
    "emissao_certificado": ("turma",),
    "revisao_nota": ("disciplina", "justificativa"),          # ACAD-003
}

_VALORES_GENERICOS = {"minha turma", "turma", "a turma", "minha", "nao informado", "não informado",
                      "n/a", "na", "-", "?", "desconhecida", "indefinida", "xxx"}


# ----------------------------------------------------------------- argumentos
class BuscarNormasArgs(BaseModel):
    """Consulta semântica à base de normas acadêmicas do Instituto Horizonte."""

    consulta: str = Field(..., min_length=3, max_length=300,
                          description="Pergunta ou palavras-chave a buscar nas normas acadêmicas.")
    top_k: Optional[int] = Field(None, ge=1, le=8,
                                 description="Quantidade de trechos a recuperar (opcional; padrão configurado).")

    @field_validator("top_k", mode="before")
    @classmethod
    def top_k_tolerante(cls, v):
        # modelos pequenos enviam "null", "" ou "3" como texto
        if isinstance(v, str):
            v = v.strip().lower()
            return None if v in {"", "null", "none"} else v
        return v


class ConsultarProtocoloArgs(BaseModel):
    """Consulta o status de um protocolo de solicitação já existente."""

    protocolo: str = Field(..., description="Número do protocolo no formato SOL-1234.")

    @field_validator("protocolo", mode="before")
    @classmethod
    def normalizar(cls, v: str) -> str:
        v = str(v).strip().upper().replace(" ", "")
        if re.fullmatch(r"SOL\d{4,6}", v):
            v = "SOL-" + v[3:]
        if not PADRAO_PROTOCOLO.match(v):
            raise ValueError("protocolo deve seguir o formato SOL-1234")
        return v


class RegistrarSolicitacaoArgs(BaseModel):
    """Registra uma NOVA solicitação no atendimento acadêmico (ação com efeito persistente)."""

    tipo: TipoSolicitacao = Field(..., description="Tipo da solicitação.")
    descricao: Optional[str] = Field(None, max_length=500,
                                     description="Descrição objetiva do pedido (opcional), sem senhas ou dados bancários.")
    turma: Optional[str] = Field(None, max_length=40, description="Código da turma informado pelo estudante (ex.: 6001).")
    disciplina: Optional[str] = Field(None, max_length=80, description="Disciplina, quando aplicável.")
    justificativa: Optional[str] = Field(None, max_length=300, description="Justificativa informada pelo estudante.")

    @field_validator("turma", "disciplina", "justificativa", mode="before")
    @classmethod
    def limpar(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        return None if v.lower() in _VALORES_GENERICOS or not v else v

    @field_validator("turma")
    @classmethod
    def turma_com_codigo(cls, v):
        if v is not None and not re.search(r"\d", v):
            raise ValueError("turma deve ser o código informado pelo estudante (ex.: 6001), não um valor genérico")
        return v

    @field_validator("descricao")
    @classmethod
    def sem_credenciais(cls, v):
        if v and re.search(r"(?i)\b(senha|password|token)\s*[:=]", v):
            raise ValueError("a descrição não pode conter senhas ou tokens (ACAD-006)")
        return v

    @model_validator(mode="after")
    def campos_por_tipo(self):
        faltando = [c for c in CAMPOS_OBRIGATORIOS_POR_TIPO.get(self.tipo, ()) if not getattr(self, c)]
        if faltando:
            raise ValueError(
                f"dados obrigatórios ausentes para '{self.tipo}': {', '.join(faltando)}. "
                "Pergunte ao estudante SOMENTE esses dados; não invente valores."
            )
        if not self.descricao:  # a descrição é derivada quando o modelo não a envia
            partes = [f"Solicitação de {self.tipo.replace('_', ' ')}"]
            partes += [f"turma {self.turma}"] if self.turma else []
            partes += [f"disciplina {self.disciplina}"] if self.disciplina else []
            partes += [self.justificativa] if self.justificativa else []
            self.descricao = " — ".join(partes)
        return self


# ------------------------------------------------------------------ resultados
class Evidencia(BaseModel):
    fonte: str
    titulo: str
    categoria: str
    score: float
    trecho: str

    @field_validator("fonte")
    @classmethod
    def fonte_valida(cls, v):
        if not PADRAO_FONTE.match(v):
            raise ValueError(f"fonte inválida: {v}")
        return v


class ResultadoBusca(BaseModel):
    ok: bool
    consulta: str
    evidencias: list[Evidencia] = []
    descartadas_abaixo_do_limiar: int = 0
    mensagem: str = ""


class ResultadoProtocolo(BaseModel):
    ok: bool
    encontrado: bool
    protocolo: str
    status: Optional[str] = None
    tipo: Optional[str] = None
    descricao: Optional[str] = None
    atualizado_em: Optional[str] = None
    mensagem: str = ""


class ResultadoRegistro(BaseModel):
    ok: bool
    protocolo: Optional[str] = None
    status: Optional[str] = None
    tipo: Optional[str] = None
    criado_em: Optional[str] = None
    mensagem: str = ""


# ------------------------------------------------------------ saída estruturada
class RespostaLLM(BaseModel):
    """Formato que o LLM deve preencher na etapa de Structured Output."""

    resposta: str = Field(..., description="Texto final para o estudante, em português.")
    fontes: list[str] = Field(default_factory=list,
                              description="IDs das fontes efetivamente usadas (ex.: ACAD-001). Vazio se nenhuma.")
    status: StatusResposta = Field(..., description="Classificação do resultado do atendimento.")
    protocolo: Optional[str] = Field(None, description="Protocolo consultado ou criado (SOL-1234), se houver.")


class RespostaAgente(BaseModel):
    """Contrato final validado e entregue ao usuário / gravado nas evidências."""

    resposta: str = Field(..., min_length=1)
    fontes: list[str] = Field(default_factory=list)
    status: StatusResposta
    protocolo: Optional[str] = None
    tools_acionadas: list[str] = Field(default_factory=list)
    rodadas: int = 0
    correcoes_validacao: list[str] = Field(default_factory=list)
    origem_estrutura: Literal["llm", "deterministico", "guardrail"] = "deterministico"

    @field_validator("fontes")
    @classmethod
    def fontes_validas(cls, v: list[str]) -> list[str]:
        for f in v:
            if not PADRAO_FONTE.match(f):
                raise ValueError(f"fonte inválida: {f}")
        return list(dict.fromkeys(v))  # remove duplicatas preservando ordem

    @field_validator("protocolo")
    @classmethod
    def protocolo_valido(cls, v):
        if v is not None and not PADRAO_PROTOCOLO.match(v):
            raise ValueError(f"protocolo inválido: {v}")
        return v

    @model_validator(mode="after")
    def coerencia(self):
        if self.status == "respondido" and not self.fontes:
            raise ValueError("status 'respondido' exige ao menos uma fonte recuperada")
        if self.status in {"solicitacao_registrada", "protocolo_consultado"} and not self.protocolo:
            raise ValueError(f"status '{self.status}' exige protocolo")
        return self
