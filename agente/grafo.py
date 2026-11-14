"""Orquestração com LangGraph.

            ┌──────────────────────┐
  START ──► │ guardrail_entrada    │──(bloqueado)──────────────────────────┐
            └──────────┬───────────┘                                       │
                       │(permitido)                                        ▼
            ┌──────────▼───────────┐  (sem tool_calls / erro / limite) ┌──────────────────┐
            │ agente (LLM + Tools) │──────────────────────────────────►│ validar_resposta │──► END
            └──────────┬───────────┘                                   └──────────────────┘
               (tool_calls)  ▲
            ┌──────────▼─────┴─────┐
            │ executar_tools       │  autorização + validação de argumentos + execução
            └──────────────────────┘  + validação do resultado (equivalente a ToolNode)

  agente ──(respondeu sem consultar nenhuma Tool, 1ª vez)──► exigir_evidencia ──► agente (instrução reforçada)

- Estado explícito (`EstadoAgente`), roteamento condicional e limite de rodadas (MAX_RODADAS),
  além do `recursion_limit` do LangGraph como segunda barreira.
- `validar_resposta` é o nó de controle/pós-processamento: Structured Output (Pydantic), checagem de
  fontes contra as evidências recuperadas, checagem de protocolo contra resultados de Tools e abstenção.
"""
from __future__ import annotations

import contextvars
import json
import operator
import re
import time
from typing import Annotated, Any, Optional, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import ValidationError

from .config import Config
from .guardrails import intencao_explicita_de_registro, validar_entrada
from .llm import ErroServicoLLM, invocar_com_retry
from .observabilidade import Tracer, TracerNulo, mascarar
from .prompts import (AVISO_INJECAO, MSG_ABSTENCAO, MSG_RECUSA_ALTERAR_NOTA, REFORCO_EVIDENCIA, STRUCTURED_PROMPT,
                      SYSTEM_PROMPT)
from .schemas import PADRAO_FONTE, PADRAO_PROTOCOLO, RespostaAgente, RespostaLLM
from .tools import MODELO_RESULTADO, TOOL_ACAO, TOOL_CONHECIMENTO, TOOL_CONSULTA, TOOLS_AUTORIZADAS

_tracer_atual: contextvars.ContextVar[Tracer] = contextvars.ContextVar("tracer", default=TracerNulo())


def _t() -> Tracer:
    return _tracer_atual.get()


class EstadoAgente(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    pergunta: str
    rodadas: int
    bloqueio: Optional[str]
    sinais: list[str]
    erro: Optional[str]
    limite_atingido: bool
    chamadas_llm: int
    reforco_evidencia: bool
    eventos_tools: Annotated[list[dict], operator.add]
    resposta_final: Optional[dict]


def _mensagens_do_turno(msgs: list[AnyMessage]) -> list[AnyMessage]:
    """Mensagens após a última HumanMessage (o turno atual)."""
    for i in range(len(msgs) - 1, -1, -1):
        if isinstance(msgs[i], HumanMessage):
            return msgs[i + 1:]
    return msgs


def _historico_recente(msgs: list[AnyMessage], turnos: int = 3) -> list[AnyMessage]:
    """Janela de contexto: últimos N turnos completos (nunca começa em ToolMessage)."""
    idx_humanas = [i for i, m in enumerate(msgs) if isinstance(m, HumanMessage)]
    inicio = idx_humanas[-turnos] if len(idx_humanas) >= turnos else 0
    return msgs[inicio:]


def _ultimas_humanas(msgs: list[AnyMessage], n: int = 2) -> list[str]:
    return [m.content for m in msgs if isinstance(m, HumanMessage)][-n:]


class Agente:
    def __init__(self, cfg: Config, llm: BaseChatModel, tools: list, checkpointer=None):
        self.cfg = cfg
        self.llm = llm
        self.tools = {t.name: t for t in tools}
        self.llm_com_tools = llm.bind_tools(tools)
        self.grafo = self._construir().compile(checkpointer=checkpointer)

    # ------------------------------------------------------------------ nós
    def no_guardrail_entrada(self, estado: EstadoAgente) -> dict:
        pergunta = _ultimas_humanas(estado["messages"], 1)[0] if estado.get("messages") else ""
        r = validar_entrada(pergunta, self.cfg.max_chars_entrada)
        _t().evento("guardrail_entrada", permitido=r.permitido, motivo=r.motivo, sinais=r.sinais,
                    pergunta=pergunta[:300])
        return {"pergunta": pergunta, "rodadas": 0, "bloqueio": None if r.permitido else r.motivo,
                "sinais": r.sinais, "erro": None, "limite_atingido": False, "chamadas_llm": 0,
                "reforco_evidencia": False, "resposta_final": None}

    def no_agente(self, estado: EstadoAgente) -> dict:
        rodada = estado.get("rodadas", 0) + 1
        instrucoes = SYSTEM_PROMPT
        if "tentativa_prompt_injection" in estado.get("sinais", []):
            instrucoes += AVISO_INJECAO
        if estado.get("reforco_evidencia"):
            instrucoes += REFORCO_EVIDENCIA
        # uma única SystemMessage no início: compatível com todos os provedores
        contexto = [SystemMessage(instrucoes)] + _historico_recente(estado["messages"])
        chamadas = estado.get("chamadas_llm", 0)
        try:
            resp = None
            for _ in range(2):  # uma nova tentativa se o modelo devolver mensagem vazia
                chamadas += 1
                resp = invocar_com_retry(lambda: self.llm_com_tools.invoke(contexto), self.cfg, _t(), "agente")
                if resp.tool_calls or (isinstance(resp.content, str) and resp.content.strip()):
                    break
                _t().evento("llm_resposta_vazia", rodada=rodada)
            else:
                return {"erro": "resposta_vazia_llm", "rodadas": rodada, "chamadas_llm": chamadas}
        except ErroServicoLLM as e:
            return {"erro": e.tipo, "rodadas": rodada, "chamadas_llm": chamadas}

        if resp.tool_calls:
            decisao = [{"tool": c["name"], "args": c["args"]} for c in resp.tool_calls]
            if rodada > self.cfg.max_rodadas:
                _t().evento("limite_rodadas_atingido", rodada=rodada, max_rodadas=self.cfg.max_rodadas,
                            tools_pedidas=decisao)
                # a AIMessage com tool_calls não é adicionada (evita tool_call sem resposta no histórico)
                return {"limite_atingido": True, "rodadas": rodada, "chamadas_llm": chamadas}
            _t().evento("decisao_agente", rodada=rodada, acao="chamar_tools", tools=decisao)
        else:
            _t().evento("decisao_agente", rodada=rodada, acao="responder", rascunho=str(resp.content)[:500])
        return {"messages": [resp], "rodadas": rodada, "chamadas_llm": chamadas}

    def no_executar_tools(self, estado: EstadoAgente) -> dict:
        ultima = estado["messages"][-1]
        humanas = _ultimas_humanas(estado["messages"], 2)
        intencao = any(intencao_explicita_de_registro(h) for h in humanas)
        ja_registrou = any(ev.get("tool") == TOOL_ACAO and ev.get("ok")
                           for ev in self._eventos_do_turno(estado))
        saidas, eventos = [], []
        for chamada in ultima.tool_calls:
            nome, args, cid = chamada["name"], chamada.get("args") or {}, chamada["id"]
            ev = {"rodada": estado.get("rodadas", 0), "tool": nome, "args": mascarar(args)}
            conteudo = None
            if nome not in TOOLS_AUTORIZADAS:
                conteudo = json.dumps({"ok": False, "erro": f"Tool '{nome}' não autorizada. "
                                       f"Tools permitidas: {sorted(TOOLS_AUTORIZADAS)}"}, ensure_ascii=False)
                ev.update(ok=False, bloqueada=True, motivo="tool_nao_autorizada")
            elif nome == TOOL_ACAO and not intencao:
                conteudo = json.dumps({"ok": False, "erro": "Ação bloqueada: o estudante não pediu explicitamente "
                                       "para registrar uma solicitação. Apenas explique o procedimento."},
                                      ensure_ascii=False)
                ev.update(ok=False, bloqueada=True, motivo="acao_sem_intencao_explicita")
            elif nome == TOOL_ACAO and ja_registrou:
                conteudo = json.dumps({"ok": False, "erro": "Já foi registrada uma solicitação neste atendimento."},
                                      ensure_ascii=False)
                ev.update(ok=False, bloqueada=True, motivo="registro_duplicado")
            else:
                tool = self.tools[nome]
                try:
                    args_validos = tool.args_schema.model_validate(args).model_dump(exclude_none=True)
                except ValidationError as e:
                    erros = "; ".join(f"{'.'.join(map(str, x['loc'])) or 'dados'}: {x['msg']}" for x in e.errors())
                    conteudo = json.dumps({"ok": False, "erro": f"argumentos inválidos: {erros}"}, ensure_ascii=False)
                    ev.update(ok=False, motivo="argumentos_invalidos", detalhe=erros[:300])
                else:
                    t0 = time.perf_counter()
                    try:
                        bruto = tool.invoke(args_validos)
                        resultado = MODELO_RESULTADO[nome].model_validate_json(bruto)
                        conteudo = resultado.model_dump_json()
                        ev.update(ok=resultado.ok, resultado=self._resumo_resultado(nome, resultado.model_dump()))
                        if nome == TOOL_ACAO and resultado.ok:
                            ja_registrou = True
                    except ValidationError as e:
                        conteudo = json.dumps({"ok": False, "erro": "resultado inválido da Tool"}, ensure_ascii=False)
                        ev.update(ok=False, motivo="resultado_invalido_tool", detalhe=str(e)[:200])
                    except Exception as e:  # noqa: BLE001
                        conteudo = json.dumps({"ok": False, "erro": f"falha na Tool: {type(e).__name__}"},
                                              ensure_ascii=False)
                        ev.update(ok=False, motivo="excecao_tool", detalhe=str(e)[:200])
                    ev["latencia_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            _t().evento("tool_execucao", **ev)
            eventos.append(ev)
            saidas.append(ToolMessage(content=conteudo, tool_call_id=cid, name=nome))
        return {"messages": saidas, "eventos_tools": eventos}

    def no_exigir_evidencia(self, estado: EstadoAgente) -> dict:
        """Nó de controle: o modelo tentou responder sem consultar nenhuma Tool (sem evidência).
        Descarta o rascunho e devolve ao agente UMA vez com instrução reforçada."""
        rascunho = estado["messages"][-1]
        _t().evento("controle_exigir_evidencia", rodada=estado.get("rodadas", 0),
                    rascunho_descartado=str(rascunho.content)[:300])
        return {"messages": [RemoveMessage(id=rascunho.id)], "reforco_evidencia": True}

    def no_validar_resposta(self, estado: EstadoAgente) -> dict:
        final = self._montar_resposta(estado)
        _t().evento("resposta_final", **final.model_dump())
        extra = {}
        if estado.get("bloqueio") or estado.get("erro") or estado.get("limite_atingido"):
            extra["messages"] = [AIMessage(final.resposta)]  # mantém o histórico coerente
        return {"resposta_final": final.model_dump(), **extra}

    # ------------------------------------------------------------- auxiliares
    @staticmethod
    def _resumo_resultado(nome: str, r: dict) -> dict:
        if nome == TOOL_CONHECIMENTO:
            return {"fontes": [(e["fonte"], e["score"]) for e in r["evidencias"]],
                    "descartadas_abaixo_do_limiar": r["descartadas_abaixo_do_limiar"], "mensagem": r["mensagem"]}
        return {k: r.get(k) for k in ("protocolo", "encontrado", "status", "tipo", "mensagem") if k in r}

    def _eventos_do_turno(self, estado: EstadoAgente) -> list[dict]:
        out = []
        for m in _mensagens_do_turno(estado.get("messages", [])):
            if isinstance(m, ToolMessage):
                try:
                    dados = json.loads(m.content)
                except (json.JSONDecodeError, TypeError):
                    continue
                out.append({"tool": m.name, "ok": dados.get("ok"), "dados": dados})
        return out

    def _evidencias_do_turno(self, estado: EstadoAgente) -> tuple[list[str], dict[str, dict], bool]:
        fontes, protocolos, houve_busca = [], {}, False
        for ev in self._eventos_do_turno(estado):
            d = ev["dados"]
            if ev["tool"] == TOOL_CONHECIMENTO and d.get("ok"):
                houve_busca = True
                fontes += [e["fonte"] for e in d.get("evidencias", [])]
            elif ev["tool"] in {TOOL_CONSULTA, TOOL_ACAO} and d.get("ok") and d.get("protocolo"):
                protocolos[d["protocolo"]] = {"tool": ev["tool"], **d}
        return list(dict.fromkeys(fontes)), protocolos, houve_busca

    def _montar_resposta(self, estado: EstadoAgente) -> RespostaAgente:
        tools_usadas =[e["tool"] for e in self._eventos_do_turno(estado)]
        base = {"tools_acionadas": tools_usadas, "rodadas": estado.get("rodadas", 0)}

        bloqueio = estado.get("bloqueio")
        if bloqueio == "acao_proibida":
            return RespostaAgente(resposta=MSG_RECUSA_ALTERAR_NOTA, status="recusado",
                                  origem_estrutura="guardrail", **base)
        if bloqueio:
            texto = {"mensagem_vazia": "Mensagem vazia. Escreva sua dúvida ou solicitação.",
                     "mensagem_muito_longa": "Mensagem muito longa. Resuma sua dúvida em poucas frases."}[bloqueio]
            return RespostaAgente(resposta=texto, status="erro", origem_estrutura="guardrail", **base)
        if estado.get("erro"):
            return RespostaAgente(
                resposta=("O serviço de IA está temporariamente indisponível "
                          f"({estado['erro']}). Tente novamente em instantes ou procure o atendimento acadêmico."),
                status="erro", origem_estrutura="guardrail", **base)

        fontes_validas, protocolos, houve_busca = self._evidencias_do_turno(estado)
        msgs_turno = _mensagens_do_turno(estado["messages"])
        rascunho = next((m.content for m in reversed(msgs_turno)
                         if isinstance(m, AIMessage) and not m.tool_calls and str(m.content).strip()), "")
        if estado.get("limite_atingido") and not rascunho:
            return RespostaAgente(
                resposta=("Não consegui concluir o atendimento dentro do limite de etapas permitido. "
                          "Reformule a pergunta ou procure o atendimento acadêmico."),
                status="erro", origem_estrutura="guardrail",
                correcoes_validacao=["limite_de_rodadas_atingido"], **base)

        correcoes: list[str] = []
        bruto, origem = None, "deterministico"
        if self.cfg.structured_output_mode == "llm":
            bruto = self._estruturar_com_llm(estado["pergunta"], rascunho, fontes_validas, protocolos, correcoes)
            origem = "llm" if bruto else "deterministico"
        if bruto is None:
            bruto = self._estruturar_deterministico(rascunho, fontes_validas, protocolos)

        # ---- validações de consistência contra o que as Tools realmente retornaram
        fontes = [f for f in bruto.fontes if f in fontes_validas]
        if len(fontes) != len(bruto.fontes):
            correcoes.append(f"fontes_removidas_nao_recuperadas:{sorted(set(bruto.fontes) - set(fontes))}")
        citadas_no_texto = [f for f in re.findall(r"ACAD-\d{3}", bruto.resposta) if f in fontes_validas]
        for f in citadas_no_texto:
            if f not in fontes:
                fontes.append(f)
        protocolo = bruto.protocolo if bruto.protocolo in protocolos else None
        if bruto.protocolo and not protocolo:
            correcoes.append(f"protocolo_descartado_nao_retornado_por_tool:{bruto.protocolo}")
        registrados = [p for p, d in protocolos.items() if d["tool"] == TOOL_ACAO]
        consultados = [p for p, d in protocolos.items() if d["tool"] == TOOL_CONSULTA]
        status, resposta = bruto.status, bruto.resposta or rascunho

        if registrados:
            protocolo = registrados[-1]
            if status != "solicitacao_registrada":
                correcoes.append(f"status_corrigido:{status}->solicitacao_registrada")
                status = "solicitacao_registrada"
        elif consultados and status not in {"protocolo_consultado"}:
            protocolo = protocolo or consultados[-1]
            correcoes.append(f"status_corrigido:{status}->protocolo_consultado")
            status = "protocolo_consultado"
        elif status in {"solicitacao_registrada", "protocolo_consultado"} and not protocolo:
            # o modelo afirmou um protocolo que nenhuma Tool retornou
            correcoes.append(f"status_sem_protocolo_real:{status}")
            humanas = _ultimas_humanas(estado["messages"], 2)
            if any(e["tool"] == TOOL_CONSULTA for e in self._eventos_do_turno(estado)):
                status = "protocolo_nao_encontrado"
            elif any(intencao_explicita_de_registro(h) for h in humanas) and "?" in rascunho:
                status = "aguardando_dados"  # pediu dados para registrar: o texto é uma pergunta legítima
            else:
                status = "respondido" if fontes_validas else "sem_evidencia"
            if re.search(r"SOL-\d+", resposta):
                correcoes.append("texto_com_protocolo_inventado_substituido")
                resposta = MSG_ABSTENCAO
                status = "sem_evidencia"

        if status == "aguardando_dados" and not registrados:
            # "aguardando dados" só existe quando há uma AÇÃO pedida pelo estudante esperando informações
            humanas = _ultimas_humanas(estado["messages"], 2)
            if not any(intencao_explicita_de_registro(h) for h in humanas):
                novo = "respondido" if (fontes or citadas_no_texto or fontes_validas) else "sem_evidencia"
                correcoes.append(f"status_corrigido:aguardando_dados_sem_acao_pedida->{novo}")
                status = novo
        if status == "respondido" and not fontes:
            if not houve_busca or not fontes_validas:
                correcoes.append("resposta_sem_evidencia_substituida_por_abstencao")
                status, resposta = "sem_evidencia", MSG_ABSTENCAO
            else:
                fontes = fontes_validas[:1]
                correcoes.append("fonte_ausente_anexada_da_evidencia_principal")
        if status == "sem_evidencia":
            fontes = []  # abstenção não cita fonte
            if not houve_busca and resposta != MSG_ABSTENCAO:
                correcoes.append("resposta_sem_consulta_a_base_substituida_por_abstencao")
                resposta = MSG_ABSTENCAO

        if fontes and not all(f in resposta for f in fontes):
            resposta = resposta.rstrip() + "\n\nFontes: " + ", ".join(fontes)
        if estado.get("limite_atingido"):
            correcoes.append("limite_de_rodadas_atingido")
        try:
            return RespostaAgente(resposta=resposta, fontes=fontes, status=status, protocolo=protocolo,
                                  correcoes_validacao=correcoes, origem_estrutura=origem, **base)
        except ValidationError as e:
            _t().evento("schema_invalido_final", detalhe=str(e)[:300])
            return RespostaAgente(resposta=resposta or MSG_ABSTENCAO, status="erro",
                                  correcoes_validacao=correcoes + ["schema_final_invalido"],
                                  origem_estrutura="deterministico", **base)

    def _estruturar_com_llm(self, pergunta, rascunho, fontes_validas, protocolos, correcoes) -> RespostaLLM | None:
        prompt = STRUCTURED_PROMPT.format(
            pergunta=pergunta, rascunho=rascunho or "(vazio)", fontes_validas=fontes_validas or "nenhuma",
            protocolos=json.dumps(protocolos, ensure_ascii=False) if protocolos else "nenhum")
        try:
            estruturado = self.llm.with_structured_output(RespostaLLM, include_raw=True)
            saida = invocar_com_retry(lambda: estruturado.invoke(prompt), self.cfg, _t(), "structured_output")
        except ErroServicoLLM as e:
            correcoes.append(f"structured_output_indisponivel:{e.tipo}")
            return None
        except Exception as e:  # noqa: BLE001 - modelos sem suporte a structured output
            _t().evento("schema_falha", etapa="structured_output", detalhe=f"{type(e).__name__}: {str(e)[:200]}")
            correcoes.append("structured_output_falhou_fallback_deterministico")
            return None
        if isinstance(saida, dict):
            parsed, erro_parse = saida.get("parsed"), saida.get("parsing_error")
        else:
            parsed, erro_parse = saida, None
        if erro_parse is not None or parsed is None:
            _t().evento("schema_falha", etapa="structured_output",
                        detalhe=str(erro_parse or "saída vazia do structured output")[:300])
            correcoes.append("structured_output_falhou_fallback_deterministico")
            return None
        if isinstance(parsed, dict):
            try:
                parsed = RespostaLLM.model_validate(parsed)
            except ValidationError as e:
                _t().evento("schema_falha", etapa="structured_output", detalhe=str(e)[:300])
                correcoes.append("structured_output_falhou_fallback_deterministico")
                return None
        if parsed.protocolo and not PADRAO_PROTOCOLO.match(parsed.protocolo):
            parsed.protocolo = None
        parsed.fontes = [f for f in parsed.fontes if PADRAO_FONTE.match(f)]
        return parsed

    @staticmethod
    def _estruturar_deterministico(rascunho, fontes_validas, protocolos) -> RespostaLLM:
        citadas = [f for f in dict.fromkeys(re.findall(r"ACAD-\d{3}", rascunho)) if f in fontes_validas]
        protocolo = next(iter(protocolos), None)
        t = rascunho.lower()
        if not rascunho.strip():
            return RespostaLLM(resposta="Não consegui gerar uma resposta. Tente reformular a pergunta.",
                               fontes=[], status="erro", protocolo=protocolo)
        if any(p in t for p in ("não encontrei", "nao encontrei", "não contém", "não há informação",
                                "não possuo", "não tenho informação", "não consta")) and not citadas:
            status = "sem_evidencia"
        elif rascunho.strip().endswith("?") and not protocolos:
            status = "aguardando_dados"
        else:
            status = "respondido"
        return RespostaLLM(resposta=rascunho or MSG_ABSTENCAO, fontes=citadas, status=status, protocolo=protocolo)

    # -------------------------------------------------------------- roteamento
    @staticmethod
    def rota_guardrail(estado: EstadoAgente) -> str:
        return "validar_resposta" if estado.get("bloqueio") else "agente"

    @staticmethod
    def rota_agente(estado: EstadoAgente) -> str:
        if estado.get("erro") or estado.get("limite_atingido"):
            return "validar_resposta"
        ultima = estado["messages"][-1]
        if isinstance(ultima, AIMessage) and ultima.tool_calls:
            return "executar_tools"
        sem_tools_no_turno = not any(isinstance(m, ToolMessage) for m in _mensagens_do_turno(estado["messages"]))
        if sem_tools_no_turno and not estado.get("reforco_evidencia"):
            return "exigir_evidencia"
        return "validar_resposta"

    def _construir(self) -> StateGraph:
        g = StateGraph(EstadoAgente)
        g.add_node("guardrail_entrada", self.no_guardrail_entrada)
        g.add_node("agente", self.no_agente)
        g.add_node("executar_tools", self.no_executar_tools)
        g.add_node("exigir_evidencia", self.no_exigir_evidencia)
        g.add_node("validar_resposta", self.no_validar_resposta)
        g.add_edge(START, "guardrail_entrada")
        g.add_conditional_edges("guardrail_entrada", self.rota_guardrail, ["agente", "validar_resposta"])
        g.add_conditional_edges("agente", self.rota_agente,
                                ["executar_tools", "exigir_evidencia", "validar_resposta"])
        g.add_edge("executar_tools", "agente")
        g.add_edge("exigir_evidencia", "agente")
        g.add_edge("validar_resposta", END)
        return g

    # ------------------------------------------------------------------ API
    def responder(self, pergunta: str, thread_id: str = "padrao", tracer: Tracer | None = None) -> dict[str, Any]:
        tracer = tracer or TracerNulo()
        token = _tracer_atual.set(tracer)
        t0 = time.perf_counter()
        tracer.evento("inicio", pergunta=(pergunta or "")[:300], thread_id=thread_id)
        config = {"configurable": {"thread_id": thread_id},
                  "recursion_limit": 2 * self.cfg.max_rodadas + 6}
        try:
            estado = self.grafo.invoke({"messages": [HumanMessage(pergunta or "")]}, config)
            final = estado["resposta_final"]
            extra = {"chamadas_llm": estado.get("chamadas_llm", 0), "limite_atingido": estado.get("limite_atingido")}
        except GraphRecursionError:
            tracer.evento("recursion_limit_langgraph", limite=config["recursion_limit"])
            final = RespostaAgente(resposta="Atendimento interrompido por limite de recursão.", status="erro",
                                   correcoes_validacao=["recursion_limit"], origem_estrutura="guardrail").model_dump()
            extra = {"chamadas_llm": None, "limite_atingido": True}
        except Exception as e:  # noqa: BLE001 - nunca derrubar o atendimento
            tracer.evento("erro_inesperado", tipo=type(e).__name__, detalhe=str(e)[:300])
            final = RespostaAgente(resposta="Ocorreu um erro interno. Tente novamente.", status="erro",
                                   origem_estrutura="guardrail").model_dump()
            extra = {"chamadas_llm": None, "limite_atingido": None}
        finally:
            _tracer_atual.reset(token)
        latencia = round(time.perf_counter() - t0, 2)
        tracer.evento("fim", status=final["status"], latencia_s=latencia, **extra)
        return {"resposta": final, "latencia_s": latencia, **extra, "trace_id": tracer.trace_id}
