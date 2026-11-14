"""Compara vários LLMs nos mesmos 10 cenários (mesmo índice, mesmas Tools, mesmo gabarito).

Uso:  python -m agente.comparar_modelos [--repeticoes N] [--apenas "qwen2.5-7b,llama3.2-3b"]

Gera evidencias/metricas/comparacao_llms.{json,md,csv} e uma pasta de execução por modelo.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .avaliacao import salvar_json
from .config import RAIZ, carregar_config
from .executar_cenarios import ICONE, rodar_modelo, slug
from .vetores import Recuperador

COLUNAS = ["acuracia_estrita", "acuracia_ponderada", "score_criterios_medio", "passou", "parcial", "falhou",
           "acerto_status", "acerto_selecao_tools", "precisao_fontes", "recall_fontes", "abstencao_correta_T09",
           "recusa_correta_T10", "chamadas_tools", "tentativas_bloqueadas", "args_invalidos", "erros_tool",
           "erros_servico_llm", "falhas_schema_structured_output", "intervencoes_exigir_evidencia", "respostas_corrigidas_pela_validacao",
           "limite_rodadas_atingido", "chamadas_llm_media", "latencia_media_s", "latencia_p95_s"]


def _pct(v):
    return "—" if v is None else f"{v:.0%}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--modelos", default=str(RAIZ / "dados" / "modelos_avaliacao.json"))
    ap.add_argument("--repeticoes", type=int, default=1)
    ap.add_argument("--apenas", help="nomes (ou parte do nome) separados por vírgula")
    ap.add_argument("--mesclar", action="store_true",
                    help="mantém na comparação os modelos já avaliados que não foram reexecutados agora")
    args = ap.parse_args()

    cfg = carregar_config()
    modelos = json.loads(Path(args.modelos).read_text(encoding="utf-8"))["llms"]
    if args.apenas:
        filtros = [f.strip().lower() for f in args.apenas.split(",")]
        modelos = [m for m in modelos if any(f in m["nome"].lower() for f in filtros)]
    recuperador = Recuperador(cfg)  # mesmo índice/embeddings para todos: só o LLM varia
    carimbo = f"{datetime.now():%Y%m%d_%H%M%S}"
    resultados, nao_executados = [], []

    for m in modelos:
        chave = ""
        if m.get("api_key_env"):
            chave = os.getenv(m["api_key_env"], "").strip()
            if not chave:
                nao_executados.append({"nome": m["nome"], "motivo": f"variável {m['api_key_env']} não configurada"})
                print(f"- {m['nome']}: pulado (sem {m['api_key_env']})")
                continue
        cfg_m = replace(cfg, llm_provider=m["provider"], llm_model=m["model"], llm_api_key=chave,
                        llm_base_url=m.get("base_url", "" if m["provider"] != cfg.llm_provider else cfg.llm_base_url))
        print(f"\n> {m['nome']}")
        dir_saida = RAIZ / "evidencias" / "execucoes" / f"{carimbo}_{slug(m['nome'])}"
        try:
            res = rodar_modelo(cfg_m, m["nome"], recuperador, dir_saida, args.repeticoes)
            resultados.append({"nome": m["nome"], "provider": m["provider"], "model": m["model"],
                               "pasta": str(dir_saida.relative_to(RAIZ)), "metricas": res["metricas"],
                               "vereditos": {f"{r['caso']}#{r['repeticao']}": r["avaliacao"]["veredito"]
                                             for r in res["registros"]},
                               "falhas": {f"{r['caso']}#{r['repeticao']}": r["avaliacao"]["criterios_falhos"]
                                          for r in res["registros"] if r["avaliacao"]["criterios_falhos"]}})
        except Exception as e:  # noqa: BLE001
            nao_executados.append({"nome": m["nome"], "motivo": f"{type(e).__name__}: {str(e)[:200]}"})
            print(f"  erro: {e}")

    saida = RAIZ / "evidencias" / "metricas"
    if args.mesclar and (saida / "comparacao_llms.json").exists():
        anterior = json.loads((saida / "comparacao_llms.json").read_text(encoding="utf-8"))
        novos = {r["nome"] for r in resultados} | {n["nome"] for n in nao_executados}
        for r in anterior["resultados"]:
            if r["nome"] not in novos:
                r.setdefault("execucao", anterior["gerado_em"])
                resultados.append(r)
        for r in resultados:
            r.setdefault("execucao", carimbo)
    resultados.sort(key=lambda r: (-r["metricas"]["acuracia_ponderada"], -r["metricas"]["score_criterios_medio"],
                                   r["metricas"]["latencia_media_s"]))
    salvar_json(saida / "comparacao_llms.json", {"gerado_em": carimbo, "config_base": cfg.resumo_seguro(),
                                                 "repeticoes": args.repeticoes, "resultados": resultados,
                                                 "nao_executados": nao_executados})
    with (saida / "comparacao_llms.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["modelo"] + COLUNAS)
        for r in resultados:
            w.writerow([r["nome"]] + [r["metricas"].get(c) for c in COLUNAS])
    (saida / "comparacao_llms.md").write_text(_markdown(resultados, nao_executados, cfg, args.repeticoes),
                                              encoding="utf-8")
    print(f"\nComparação: {saida / 'comparacao_llms.md'}")


def _markdown(resultados, nao_executados, cfg, repeticoes) -> str:
    md = ["# Comparação de LLMs nos 10 cenários", "",
          f"Gerado em {datetime.now():%d/%m/%Y %H:%M}. Mesmo índice vetorial (`{cfg.embedding_provider}:"
          f"{cfg.embedding_model}`, Top-K {cfg.rag_top_k}, limiar {cfg.rag_score_min}), mesmas Tools, mesmo grafo e "
          f"mesmo gabarito — só o LLM muda. Repetições por cenário: {repeticoes}.", "",
          "## Ranking", "",
          "| # | Modelo | Acurácia estrita | Acurácia ponderada | Score critérios | ✅ | 🟡 | ❌ | Latência média | p95 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(resultados, 1):
        m = r["metricas"]
        md.append(f"| {i} | {r['nome']} | {_pct(m['acuracia_estrita'])} | {_pct(m['acuracia_ponderada'])} | "
                  f"{_pct(m['score_criterios_medio'])} | {m['passou']} | {m['parcial']} | {m['falhou']} | "
                  f"{m['latencia_media_s']}s | {m['latencia_p95_s']}s |")
    md += ["", "Acurácia estrita = cenários que passaram ÷ total. Ponderada = (passou + 0,5 × parcial) ÷ total. "
           "Score de critérios = média da fração de critérios atendidos por cenário.", "",
           "## Qualidade por dimensão", "",
           "| Modelo | Status correto | Seleção de Tools | Precisão fontes | Recall fontes | Abstenção T09 | Recusa T10 |",
           "|---|---|---|---|---|---|---|"]
    for r in resultados:
        m = r["metricas"]
        md.append(f"| {r['nome']} | {_pct(m['acerto_status'])} | {_pct(m['acerto_selecao_tools'])} | "
                  f"{_pct(m['precisao_fontes'])} | {_pct(m['recall_fontes'])} | {_pct(m['abstencao_correta_T09'])} | "
                  f"{_pct(m['recusa_correta_T10'])} |")
    md += ["", "## Erros e intervenções de segurança", "",
           "| Modelo | Chamadas de Tools | Tentativas bloqueadas | Args inválidos | Erros de Tool | Erros serviço LLM |"
           " Falhas schema | Respondeu sem consultar (intervenções) | Respostas corrigidas | Limite de rodadas |"
           " Chamadas LLM/turno |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in resultados:
        m = r["metricas"]
        md.append(f"| {r['nome']} | {m['chamadas_tools']} | {m['tentativas_bloqueadas']} | {m['args_invalidos']} | "
                  f"{m['erros_tool']} | {m['erros_servico_llm']} | {m['falhas_schema_structured_output']} | "
                  f"{m['intervencoes_exigir_evidencia']} | "
                  f"{m['respostas_corrigidas_pela_validacao']} | {m['limite_rodadas_atingido']} | "
                  f"{m['chamadas_llm_media']} |")
    if resultados:
        chaves = list(resultados[0]["vereditos"].keys())
        md += ["", "## Matriz cenário × modelo", "", "| Cenário | " + " | ".join(r["nome"] for r in resultados) + " |",
               "|---|" + "---|" * len(resultados)]
        for k in chaves:
            md.append(f"| {k.replace('#1', '') if repeticoes == 1 else k} | " +
                      " | ".join(ICONE.get(r["vereditos"].get(k), "—") for r in resultados) + " |")
        md += ["", "## Critérios não atendidos por modelo", ""]
        for r in resultados:
            md.append(f"**{r['nome']}** (detalhes em `{r['pasta']}/relatorio.md`)")
            if not r["falhas"]:
                md.append("- nenhum")
            for caso, falhos in r["falhas"].items():
                md.append(f"- {caso.replace('#1', '') if repeticoes == 1 else caso}: {', '.join(falhos)}")
            md.append("")
    if nao_executados:
        md += ["## Não executados", ""] + [f"- **{n['nome']}**: {n['motivo']}" for n in nao_executados]
    return "\n".join(md)


if __name__ == "__main__":
    main()
