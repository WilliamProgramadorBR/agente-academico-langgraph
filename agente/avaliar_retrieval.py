"""Comparação de modelos de embeddings no retrieval (Qdrant em memória, isolado do índice principal).

Uso:  python -m agente.avaliar_retrieval
Métricas por modelo: Hit@1, Hit@3, MRR, score médio do documento correto, maior score em pergunta sem
resposta na base (T09), margem de separação e limiar sugerido para abstenção.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from qdrant_client import QdrantClient

from .avaliacao import carregar_cenarios, carregar_gabarito, salvar_json
from .config import RAIZ, carregar_config
from .embeddings import criar_embeddings
from .vetores import Recuperador, carregar_documentos, indexar


def avaliar_modelo(cfg, docs, cenarios, gabarito, top_k: int = 3) -> dict:
    cfg = replace(cfg, rag_score_min=-1.0, qdrant_collection="avaliacao_retrieval")
    t0 = time.perf_counter()
    emb = criar_embeddings(cfg)
    cliente = QdrantClient(":memory:")
    indexar(cfg, docs, embeddings=emb, cliente=cliente)  # cliente em memória: isolado do índice real
    t_index = time.perf_counter() - t0
    rec = Recuperador(cfg, embeddings=emb, cliente=cliente)

    linhas, hits1, hits3, rr, score_ok, top1_neg = [], 0, 0, [], [], []
    t1 = time.perf_counter()
    for c in cenarios:
        g = gabarito[c["caso"]]
        relevantes = set(g.get("fontes_relevantes_busca") or g.get("fontes_esperadas") or [])
        negativo = bool(g.get("fontes_proibidas_qualquer"))
        if not relevantes and not negativo:
            continue
        evid, _ = rec.buscar(c["pergunta"], top_k)
        ranking = [(e["fonte"], e["score"]) for e in evid]
        linha = {"caso": c["caso"], "relevantes": sorted(relevantes), "ranking": ranking}
        if negativo:
            top1_neg.append(ranking[0][1])
            linha["tipo"] = "negativo (sem resposta na base)"
        else:
            pos = next((i for i, (f, _) in enumerate(ranking, 1) if f in relevantes), None)
            hits1 += pos == 1
            hits3 += pos is not None and pos <= 3
            rr.append(1 / pos if pos else 0.0)
            if pos:
                score_ok.append(ranking[pos - 1][1])
            linha.update(tipo="positivo", posicao_relevante=pos)
        linhas.append(linha)
    t_busca = (time.perf_counter() - t1) / max(1, len(linhas))
    cliente.close()

    n = len(rr)
    menor_ok = min(score_ok) if score_ok else 0.0
    maior_neg = max(top1_neg) if top1_neg else 0.0
    margem = menor_ok - maior_neg
    return {
        "hit@1": round(hits1 / n, 4), "hit@3": round(hits3 / n, 4), "mrr": round(sum(rr) / n, 4),
        "score_medio_relevante": round(sum(score_ok) / len(score_ok), 4) if score_ok else None,
        "menor_score_relevante": round(menor_ok, 4),
        "maior_score_negativo_T09": round(maior_neg, 4),
        "margem_separacao": round(margem, 4),
        "limiar_sugerido": round((menor_ok + maior_neg) / 2, 3) if margem > 0 else None,
        "indexacao_s": round(t_index, 2), "busca_media_ms": round(t_busca * 1000, 1),
        "detalhes": linhas,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--modelos", default=str(RAIZ / "dados" / "modelos_avaliacao.json"))
    ap.add_argument("--top-k", type=int, default=3)
    args = ap.parse_args()

    cfg = carregar_config()
    docs = carregar_documentos(cfg.base_conhecimento)
    cenarios = carregar_cenarios(str(RAIZ / "dados" / "cenarios_de_teste_aluno.csv"))
    gabarito = carregar_gabarito(str(RAIZ / "dados" / "gabarito_cenarios.json"))
    modelos = json.loads(Path(args.modelos).read_text(encoding="utf-8"))["embeddings"]

    resultados = []
    for m in modelos:
        print(f"> {m['nome']} ...", flush=True)
        cfg_m = replace(cfg, embedding_provider=m["provider"], embedding_model=m["model"])
        try:
            r = avaliar_modelo(cfg_m, docs, cenarios, gabarito, args.top_k)
            resultados.append({"nome": m["nome"], "provider": m["provider"], "model": m["model"], **r})
            print(f"  hit@1={r['hit@1']} hit@3={r['hit@3']} mrr={r['mrr']} margem={r['margem_separacao']}")
        except Exception as e:  # noqa: BLE001
            resultados.append({"nome": m["nome"], "erro": f"{type(e).__name__}: {str(e)[:200]}"})
            print(f"  erro: {e}")

    saida = RAIZ / "evidencias" / "metricas"
    salvar_json(saida / "retrieval_embeddings.json",
                {"gerado_em": datetime.now().isoformat(timespec="seconds"), "top_k": args.top_k,
                 "resultados": resultados})
    ok = sorted([r for r in resultados if "erro" not in r], key=lambda r: (-r["mrr"], -r["margem_separacao"]))
    md = ["# Comparação de embeddings (retrieval)", "",
          f"Gerado em {datetime.now():%d/%m/%Y %H:%M}. Top-K = {args.top_k}. Positivos: T01, T02, T03, T05, T06, "
          "T07, T08 (documento relevante conhecido). Negativo: T09 (a base não tem a resposta).", "",
          "| # | Modelo | Hit@1 | Hit@3 | MRR | Score médio relevante | Maior score T09 | Margem | Limiar sugerido |"
          " Busca (ms) |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(ok, 1):
        md.append(f"| {i} | {r['nome']} | {r['hit@1']:.2f} | {r['hit@3']:.2f} | {r['mrr']:.3f} | "
                  f"{r['score_medio_relevante']:.3f} | {r['maior_score_negativo_T09']:.3f} | "
                  f"{r['margem_separacao']:+.3f} | {r['limiar_sugerido'] or '—'} | {r['busca_media_ms']} |")
    for r in resultados:
        if "erro" in r:
            md.append(f"\n- **{r['nome']}**: não executado ({r['erro']})")
    md += ["", "Margem = menor score do documento correto − maior score obtido na pergunta sem resposta. "
           "Margem positiva significa que existe um limiar que separa evidência real de ruído.", "",
           "## Ranking por pergunta (top-3)", ""]
    for r in ok:
        md.append(f"### {r['nome']}")
        for d in r["detalhes"]:
            rk = ", ".join(f"{f} ({s:.2f})" for f, s in d["ranking"])
            marca = "" if d["tipo"] != "positivo" else f" — relevante na posição {d['posicao_relevante'] or 'não encontrado'}"
            md.append(f"- {d['caso']} [{d['tipo']}]: {rk}{marca}")
        md.append("")
    (saida / "retrieval_embeddings.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\nRelatório: {saida / 'retrieval_embeddings.md'}")


if __name__ == "__main__":
    main()
