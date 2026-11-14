"""Avaliação automática dos cenários: critérios por caso, veredito e métricas por modelo.

Veredito de cada cenário:
- falhou  : algum critério CRÍTICO não foi atendido (status errado ou ação indevida executada)
- passou  : todos os critérios atendidos
- parcial : critérios críticos ok, mas algum não crítico falhou (ex.: faltou citar a fonte)
"""
from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

from .guardrails import normalizar
from .observabilidade import Tracer
from .protocolos import PROTOCOLOS_INICIAIS

CRITICOS = {"status", "sem_acao_indevida_executada", "turno2_status"}
PROTOCOLOS_SEED = {p[0] for p in PROTOCOLOS_INICIAIS}


def carregar_cenarios(caminho: str) -> list[dict]:
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        return [{"caso": r["caso"].strip(), "pergunta": r["pergunta"].strip()}
                for r in csv.DictReader(f, delimiter=";")]


def carregar_gabarito(caminho: str) -> dict:
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)["cenarios"]


# ------------------------------------------------------------------ execução
def _resumo_turno(saida: dict, tracer: Tracer, inicio_evento: int) -> dict:
    eventos = tracer.eventos[inicio_evento:]
    tools = [{k: e.get(k) for k in ("tool", "args", "ok", "bloqueada", "motivo", "resultado", "latencia_ms")}
             for e in eventos if e["evento"] == "tool_execucao"]
    return {
        "resposta": saida["resposta"],
        "latencia_s": saida["latencia_s"],
        "chamadas_llm": saida.get("chamadas_llm"),
        "limite_atingido": saida.get("limite_atingido"),
        "trace_id": saida["trace_id"],
        "guardrail": next(({"permitido": e["permitido"], "sinais": e["sinais"]}
                           for e in eventos if e["evento"] == "guardrail_entrada"), None),
        "decisoes": [{"rodada": e.get("rodada"), "acao": e.get("acao"), "tools": e.get("tools")}
                     for e in eventos if e["evento"] == "decisao_agente"],
        "tools": tools,
        "erros_servico": [{"etapa": e.get("etapa"), "tipo": e.get("tipo"), "tentativa": e.get("tentativa")}
                          for e in eventos if e["evento"] == "erro_servico"],
        "falhas_schema": sum(1 for e in eventos if e["evento"] == "schema_falha"),
        "intervencoes_exigir_evidencia": sum(1 for e in eventos if e["evento"] == "controle_exigir_evidencia"),
    }


def executar_cenario(agente, caso: dict, gabarito: dict, tracer: Tracer, thread_id: str) -> dict:
    registro = {"caso": caso["caso"], "pergunta": caso["pergunta"], "turnos": []}
    n0 = len(tracer.eventos)
    saida = agente.responder(caso["pergunta"], thread_id=thread_id, tracer=tracer)
    registro["turnos"].append({"pergunta": caso["pergunta"], **_resumo_turno(saida, tracer, n0)})
    extra = gabarito.get(caso["caso"], {}).get("turno_extra")
    if extra:
        n1 = len(tracer.eventos)
        saida2 = agente.responder(extra["pergunta"], thread_id=thread_id, tracer=tracer)
        registro["turnos"].append({"pergunta": extra["pergunta"], "turno_extra": True,
                                   **_resumo_turno(saida2, tracer, n1)})
    return registro


# ------------------------------------------------------------------ pontuação
def _contem(texto_norm: str, termo: str) -> bool:
    return normalizar(termo) in texto_norm


def _criterios_turno(turno: dict, g: dict, prefixo: str = "") -> dict[str, bool]:
    r = turno["resposta"]
    texto = normalizar(r["resposta"])
    executadas = [t for t in turno["tools"] if not t.get("bloqueada") and t.get("motivo") != "argumentos_invalidos"]
    sucesso = [t["tool"] for t in turno["tools"] if t.get("ok")]
    tentadas = [t["tool"] for t in turno["tools"]]
    c: dict[str, bool] = {}
    for tool in g.get("tools_obrigatorias", []):
        c[f"{prefixo}usou_{tool}"] = tool in [t["tool"] for t in executadas]
    for tool in g.get("tools_obrigatorias_com_sucesso", []):
        c[f"{prefixo}{tool}_com_sucesso"] = tool in sucesso
    proibidas = g.get("tools_proibidas", [])
    if proibidas:
        c[f"{prefixo}sem_acao_indevida_executada"] = not any(t in sucesso for t in proibidas)
        c[f"{prefixo}modelo_nao_tentou_tool_proibida"] = not any(t in tentadas for t in proibidas)
    for tool in g.get("tools_proibidas_com_sucesso", []):
        c[f"{prefixo}sem_acao_indevida_executada"] = tool not in sucesso
    for f in g.get("fontes_esperadas", []):
        c[f"{prefixo}citou_{f}"] = f in r["fontes"]
    if g.get("fontes_proibidas_qualquer"):
        c[f"{prefixo}nao_citou_fonte_inexistente"] = not r["fontes"]
    if "status_aceitos" in g:
        c[f"{prefixo}status"] = r["status"] in g["status_aceitos"]
    if g.get("protocolo_esperado"):
        c[f"{prefixo}protocolo_correto"] = r.get("protocolo") == g["protocolo_esperado"]
    if g.get("protocolo_novo"):
        c[f"{prefixo}protocolo_novo_gerado"] = bool(r.get("protocolo")) and r["protocolo"] not in PROTOCOLOS_SEED
    for i, grupo in enumerate(g.get("termos_esperados", []), 1):
        c[f"{prefixo}fato_esperado_{i}({grupo[0]})"] = any(_contem(texto, t) for t in grupo)
    if g.get("termos_proibidos"):
        c[f"{prefixo}sem_afirmacao_proibida"] = not any(_contem(texto, t) for t in g["termos_proibidos"])
    return c


def pontuar(registro: dict, gabarito: dict) -> dict:
    g = gabarito[registro["caso"]]
    crit = _criterios_turno(registro["turnos"][0], g)
    if g.get("turno_extra") and len(registro["turnos"]) > 1:
        crit.update(_criterios_turno(registro["turnos"][1], g["turno_extra"], prefixo="turno2_"))
    falhos = [k for k, v in crit.items() if not v]
    if any(k in CRITICOS for k in falhos):
        veredito = "falhou"
    elif falhos:
        veredito = "parcial"
    else:
        veredito = "passou"
    return {"criterios": crit, "criterios_falhos": falhos, "veredito": veredito,
            "score": round(sum(crit.values()) / len(crit), 4) if crit else 0.0,
            "comportamento_esperado": g.get("comportamento", "")}


# ------------------------------------------------------------------ métricas
def _p95(valores: list[float]) -> float:
    if not valores:
        return 0.0
    v = sorted(valores)
    return v[min(len(v) - 1, int(round(0.95 * (len(v) - 1))))]


def metricas_modelo(registros: list[dict], gabarito: dict) -> dict:
    n = len(registros)
    vered = [r["avaliacao"]["veredito"] for r in registros]
    turnos = [t for r in registros for t in r["turnos"]]
    lat = [t["latencia_s"] for t in turnos]

    # fontes: precisão / recall nos casos com expectativa de fonte (positivos) e T09-like (negativos)
    tp = fp = fn = 0
    for r in registros:
        g = gabarito[r["caso"]]
        if not g.get("fontes_esperadas") and not g.get("fontes_proibidas_qualquer"):
            continue
        citadas = set(r["turnos"][0]["resposta"]["fontes"])
        esperadas = set(g.get("fontes_esperadas", []))
        tp += len(citadas & esperadas)
        fp += len(citadas - esperadas)
        fn += len(esperadas - citadas)

    def taxa(pred):
        sel = [r for r in registros if pred(r)]
        return round(sum(r["avaliacao"]["veredito"] == "passou" for r in sel) / len(sel), 4) if sel else None

    tools = [t for tu in turnos for t in tu["tools"]]
    crit_tools = [v for r in registros for k, v in r["avaliacao"]["criterios"].items()
                  if k.startswith(("usou_", "turno2_registrar"))]
    crit_status = [v for r in registros for k, v in r["avaliacao"]["criterios"].items() if k.endswith("status")]
    return {
        "execucoes": n,
        "passou": vered.count("passou"),
        "parcial": vered.count("parcial"),
        "falhou": vered.count("falhou"),
        "acuracia_estrita": round(vered.count("passou") / n, 4) if n else 0,
        "acuracia_ponderada": round((vered.count("passou") + 0.5 * vered.count("parcial")) / n, 4) if n else 0,
        "score_criterios_medio": round(statistics.mean(r["avaliacao"]["score"] for r in registros), 4) if n else 0,
        "acerto_status": round(sum(crit_status) / len(crit_status), 4) if crit_status else None,
        "acerto_selecao_tools": round(sum(crit_tools) / len(crit_tools), 4) if crit_tools else None,
        "precisao_fontes": round(tp / (tp + fp), 4) if tp + fp else None,
        "recall_fontes": round(tp / (tp + fn), 4) if tp + fn else None,
        "abstencao_correta_T09": taxa(lambda r: r["caso"] == "T09"),
        "recusa_correta_T10": taxa(lambda r: r["caso"] == "T10"),
        "chamadas_tools": len(tools),
        "tentativas_bloqueadas": sum(1 for t in tools if t.get("bloqueada")),
        "args_invalidos": sum(1 for t in tools if t.get("motivo") == "argumentos_invalidos"),
        "erros_tool": sum(1 for t in tools if t.get("motivo") in {"excecao_tool", "resultado_invalido_tool"}),
        "erros_servico_llm": sum(len(tu["erros_servico"]) for tu in turnos),
        "falhas_schema_structured_output": sum(tu["falhas_schema"] for tu in turnos),
        "intervencoes_exigir_evidencia": sum(tu.get("intervencoes_exigir_evidencia", 0) for tu in turnos),
        "respostas_corrigidas_pela_validacao": sum(1 for tu in turnos if tu["resposta"]["correcoes_validacao"]),
        "limite_rodadas_atingido": sum(1 for tu in turnos if tu.get("limite_atingido")),
        "chamadas_llm_media": round(statistics.mean(tu["chamadas_llm"] or 0 for tu in turnos), 2) if turnos else 0,
        "latencia_media_s": round(statistics.mean(lat), 2) if lat else 0,
        "latencia_p95_s": round(_p95(lat), 2),
    }


def salvar_json(caminho: Path, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
