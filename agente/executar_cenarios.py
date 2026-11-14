"""Executa os 10 cenários de teste com o LLM configurado no .env e gera evidências.

Uso:  python -m agente.executar_cenarios [--repeticoes N] [--casos T01,T04]

Saída em evidencias/execucoes/<data>_<modelo>/:
  resultados.json  -> registro completo (decisões, Tools, argumentos, resultados, respostas, critérios)
  relatorio.md     -> tabela passou/parcial/falhou + evidências por cenário
Trace bruto (JSONL, segredos mascarados) em evidencias/logs/.
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

from .avaliacao import (carregar_cenarios, carregar_gabarito, executar_cenario, metricas_modelo, pontuar,
                        salvar_json)
from .config import RAIZ, Config, carregar_config
from .fabrica import montar_agente
from .observabilidade import Tracer
from .vetores import Recuperador

ICONE = {"passou": "✅ passou", "parcial": "🟡 parcial", "falhou": "❌ falhou"}


def slug(texto: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()[:40]


def rodar_modelo(cfg: Config, nome: str, recuperador: Recuperador, dir_saida: Path, repeticoes: int = 1,
                 casos: list[str] | None = None) -> dict:
    cenarios = carregar_cenarios(str(RAIZ / "dados" / "cenarios_de_teste_aluno.csv"))
    if casos:
        cenarios = [c for c in cenarios if c["caso"] in casos]
    gabarito = carregar_gabarito(str(RAIZ / "dados" / "gabarito_cenarios.json"))
    dir_saida.mkdir(parents=True, exist_ok=True)
    db = dir_saida / "protocolos.db"  # banco novo por execução: SOL-1001..1003 sempre no estado inicial
    if db.exists():
        db.unlink()
    agente = montar_agente(cfg, recuperador=recuperador, db_protocolos=str(db))
    registros = []
    for rep in range(1, repeticoes + 1):
        for c in cenarios:
            tracer = Tracer(cfg.log_dir, console=cfg.log_console, rotulo=f"{nome}|{c['caso']}|rep{rep}")
            print(f"  [{nome}] {c['caso']} (rep {rep}) ...", end=" ", flush=True)
            reg = executar_cenario(agente, c, gabarito, tracer, thread_id=f"{c['caso']}-rep{rep}")
            reg["repeticao"] = rep
            reg["avaliacao"] = pontuar(reg, gabarito)
            registros.append(reg)
            print(f"{reg['avaliacao']['veredito']} ({reg['turnos'][0]['latencia_s']}s)", flush=True)
    resultado = {
        "modelo": nome, "config": cfg.resumo_seguro(), "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "repeticoes": repeticoes, "metricas": metricas_modelo(registros, gabarito), "registros": registros,
    }
    salvar_json(dir_saida / "resultados.json", resultado)
    (dir_saida / "relatorio.md").write_text(relatorio_markdown(resultado), encoding="utf-8")
    return resultado


def _fmt_tools(turno: dict) -> str:
    partes = []
    for t in turno["tools"]:
        marca = "✓" if t.get("ok") else ("⛔" if t.get("bloqueada") else "✗")
        partes.append(f"{t['tool']}{marca}")
    return ", ".join(partes) or "—"


def relatorio_markdown(res: dict) -> str:
    m = res["metricas"]
    cfg = res["config"]
    linhas = [
        f"# Execução dos cenários — {res['modelo']}", "",
        f"Gerado em {res['gerado_em']} · LLM `{cfg['llm_provider']}:{cfg['llm_model']}` · embeddings "
        f"`{cfg['embedding_provider']}:{cfg['embedding_model']}` · {cfg['vector_store']} · Top-K {cfg['rag_top_k']} · "
        f"limiar {cfg['rag_score_min']} · máx. rodadas {cfg['max_rodadas']} · structured output "
        f"`{cfg['structured_output_mode']}`", "",
        f"**Resultado:** {m['passou']} passou · {m['parcial']} parcial · {m['falhou']} falhou — acurácia estrita "
        f"{m['acuracia_estrita']:.0%}, ponderada {m['acuracia_ponderada']:.0%}, latência média "
        f"{m['latencia_media_s']}s", "",
        "Legenda das Tools: ✓ executada com sucesso · ✗ erro/argumento inválido · ⛔ bloqueada pela política", "",
        "| Caso | Pergunta | Resultado | Status | Tools | Fontes | Protocolo | Latência |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in res["registros"]:
        for i, t in enumerate(r["turnos"]):
            caso = r["caso"] + (" (turno 2)" if i else "") + (f" rep{r['repeticao']}" if res["repeticoes"] > 1 else "")
            ver = ICONE[r["avaliacao"]["veredito"]] if i == 0 else "↳"
            linhas.append(
                f"| {caso} | {t['pergunta']} | {ver} | `{t['resposta']['status']}` | {_fmt_tools(t)} | "
                f"{', '.join(t['resposta']['fontes']) or '—'} | {t['resposta'].get('protocolo') or '—'} | "
                f"{t['latencia_s']}s |")
    linhas += ["", "## Evidências por cenário", ""]
    for r in res["registros"]:
        a = r["avaliacao"]
        linhas += [f"### {r['caso']} — {ICONE[a['veredito']]}", "",
                   f"**Esperado:** {a['comportamento_esperado']}", ""]
        for i, t in enumerate(r["turnos"]):
            if i:
                linhas.append("**Turno 2 (dados complementares):**")
            linhas.append(f"**Pergunta:** {t['pergunta']}  ")
            g = t.get("guardrail") or {}
            linhas.append(f"**Guardrail de entrada:** {'permitido' if g.get('permitido') else 'bloqueado'}"
                          f"{' · sinais: ' + ', '.join(g['sinais']) if g.get('sinais') else ''}  ")
            for d in t["decisoes"]:
                alvo = ", ".join(f"{x['tool']}({x['args']})" for x in d["tools"] or []) if d["tools"] else "resposta final"
                linhas.append(f"- Rodada {d['rodada']}: decisão `{d['acao']}` → {alvo}")
            for tool in t["tools"]:
                info = tool.get("resultado") or tool.get("motivo")
                linhas.append(f"- Tool `{tool['tool']}` ok={tool.get('ok')} → {info}")
            for e in t["erros_servico"]:
                linhas.append(f"- ⚠️ erro de serviço {e['tipo']} na etapa {e['etapa']} (tentativa {e['tentativa']})")
            resp = t["resposta"]
            linhas += ["", "> " + resp["resposta"].replace("\n", "\n> "), "",
                       f"Status `{resp['status']}` · fontes {resp['fontes'] or '[]'} · protocolo "
                       f"{resp.get('protocolo')} · estrutura via `{resp['origem_estrutura']}` · correções: "
                       f"{resp['correcoes_validacao'] or 'nenhuma'} · trace `{t['trace_id']}`", ""]
        if a["criterios_falhos"]:
            linhas.append(f"**Critérios não atendidos:** {', '.join(a['criterios_falhos'])}")
        linhas.append("")
    return "\n".join(linhas)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repeticoes", type=int, default=1)
    ap.add_argument("--casos", help="lista separada por vírgula, ex.: T01,T04")
    args = ap.parse_args()
    cfg = carregar_config()
    nome = f"{cfg.llm_provider}:{cfg.llm_model}"
    dir_saida = RAIZ / "evidencias" / "execucoes" / f"{datetime.now():%Y%m%d_%H%M%S}_{slug(nome)}"
    res = rodar_modelo(cfg, nome, Recuperador(cfg), dir_saida, args.repeticoes,
                       args.casos.split(",") if args.casos else None)
    m = res["metricas"]
    print(f"\n{m['passou']} passou · {m['parcial']} parcial · {m['falhou']} falhou  →  {dir_saida / 'relatorio.md'}")


if __name__ == "__main__":
    main()
