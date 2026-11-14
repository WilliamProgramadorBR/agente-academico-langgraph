"""Tools tipadas (LangChain) do agente.

- buscar_normas         -> Tool de CONHECIMENTO (RAG no Qdrant)
- consultar_protocolo   -> Tool de CONSULTA (SQLite, somente leitura)
- registrar_solicitacao -> Tool de AÇÃO (SQLite, escrita; exige intenção explícita - ver grafo.py)

Todas retornam JSON validado por um modelo Pydantic de resultado. Erros internos
viram um resultado `ok=false` em vez de exceção, para o LLM poder reagir.
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, StructuredTool

from .protocolos import RepositorioProtocolos
from .schemas import (
    BuscarNormasArgs,
    ConsultarProtocoloArgs,
    RegistrarSolicitacaoArgs,
    ResultadoBusca,
    ResultadoProtocolo,
    ResultadoRegistro,
)
from .vetores import Recuperador

TOOL_CONHECIMENTO = "buscar_normas"
TOOL_CONSULTA = "consultar_protocolo"
TOOL_ACAO = "registrar_solicitacao"
TOOLS_AUTORIZADAS = {TOOL_CONHECIMENTO, TOOL_CONSULTA, TOOL_ACAO}
TOOLS_COM_EFEITO = {TOOL_ACAO}

MODELO_RESULTADO = {
    TOOL_CONHECIMENTO: ResultadoBusca,
    TOOL_CONSULTA: ResultadoProtocolo,
    TOOL_ACAO: ResultadoRegistro,
}


def criar_tools(recuperador: Recuperador, repositorio: RepositorioProtocolos) -> list[BaseTool]:
    def buscar_normas(consulta: str, top_k: int | None = None) -> str:
        try:
            evidencias, descartadas = recuperador.buscar(consulta, top_k)
        except Exception as e:  # serviço vetorial/embeddings indisponível
            return ResultadoBusca(ok=False, consulta=consulta,
                                  mensagem=f"falha no serviço de busca: {type(e).__name__}").model_dump_json()
        msg = ("" if evidencias else
               "Nenhuma evidência acima do limiar de similaridade. Não responda com base em suposições; "
               "informe que a base não contém essa informação.")
        return ResultadoBusca(ok=True, consulta=consulta, evidencias=evidencias,
                              descartadas_abaixo_do_limiar=descartadas, mensagem=msg).model_dump_json()

    def consultar_protocolo(protocolo: str) -> str:
        try:
            reg = repositorio.consultar(protocolo)
        except Exception as e:
            return ResultadoProtocolo(ok=False, encontrado=False, protocolo=protocolo,
                                      mensagem=f"falha no sistema de solicitações: {type(e).__name__}"
                                      ).model_dump_json()
        if not reg:
            return ResultadoProtocolo(ok=True, encontrado=False, protocolo=protocolo,
                                      mensagem="Protocolo não encontrado. Não invente status."
                                      ).model_dump_json()
        return ResultadoProtocolo(ok=True, encontrado=True, protocolo=reg["protocolo"], status=reg["status"],
                                  tipo=reg["tipo"], descricao=reg["descricao"],
                                  atualizado_em=reg["atualizado_em"]).model_dump_json()

    def registrar_solicitacao(tipo: str, descricao: str, turma: str | None = None,
                              disciplina: str | None = None, justificativa: str | None = None) -> str:
        try:
            reg = repositorio.registrar(tipo, descricao, turma, disciplina, justificativa)
        except Exception as e:
            return ResultadoRegistro(ok=False, mensagem=f"falha ao persistir: {type(e).__name__}").model_dump_json()
        return ResultadoRegistro(ok=True, protocolo=reg["protocolo"], status=reg["status"], tipo=reg["tipo"],
                                 criado_em=reg["criado_em"],
                                 mensagem="Solicitação registrada. O prazo é informado no protocolo."
                                 ).model_dump_json()

    return [
        StructuredTool.from_function(
            buscar_normas, name=TOOL_CONHECIMENTO, args_schema=BuscarNormasArgs,
            description=("Busca trechos das normas acadêmicas oficiais (fictícias) do Instituto Horizonte. "
                         "Use para QUALQUER dúvida sobre regras, prazos, procedimentos e políticas. "
                         "Retorna evidências com o ID da fonte (ACAD-xxx)."),
        ),
        StructuredTool.from_function(
            consultar_protocolo, name=TOOL_CONSULTA, args_schema=ConsultarProtocoloArgs,
            description="Consulta o status atual de um protocolo existente (formato SOL-1234). Somente leitura.",
        ),
        StructuredTool.from_function(
            registrar_solicitacao, name=TOOL_ACAO, args_schema=RegistrarSolicitacaoArgs,
            description=("Registra uma NOVA solicitação no atendimento acadêmico e devolve o protocolo. "
                         "Use SOMENTE quando o estudante pedir explicitamente para abrir/registrar uma solicitação "
                         "e todos os dados obrigatórios tiverem sido informados por ele. "
                         "segunda_via_certificado exige turma e justificativa; revisao_nota exige disciplina e "
                         "justificativa. Nunca invente esses dados."),
        ),
    ]
