"""Ingestão da base acadêmica no Qdrant.

Uso:  python -m agente.indexar            (indexa os 12 documentos)
      python -m agente.indexar --testar "frequência mínima"   (indexa e faz uma busca)
"""
from __future__ import annotations

import argparse
import json

from .config import carregar_config
from .observabilidade import Tracer
from .vetores import Recuperador, carregar_documentos, indexar


def main() -> None:
    parser = argparse.ArgumentParser(description="Indexa a base de conhecimento acadêmica no Qdrant.")
    parser.add_argument("--testar", metavar="CONSULTA", help="faz uma busca de teste após indexar")
    args = parser.parse_args()

    cfg = carregar_config()
    tracer = Tracer(cfg.log_dir, rotulo="indexacao")
    docs = carregar_documentos(cfg.base_conhecimento)
    resumo, cliente = indexar(cfg, docs)
    tracer.evento("indexacao_concluida", **resumo, config=cfg.resumo_seguro())
    print(json.dumps(resumo, ensure_ascii=False, indent=2))

    if args.testar:
        rec = Recuperador(cfg, cliente=cliente)
        evid, desc = rec.buscar(args.testar)
        tracer.evento("busca_teste", consulta=args.testar, fontes=[e["fonte"] for e in evid], descartadas=desc)
        for e in evid:
            print(f"  {e['fonte']}  score={e['score']:.3f}  {e['titulo']}")
        print(f"  ({desc} resultado(s) abaixo do limiar {cfg.rag_score_min})")
    cliente.close()


if __name__ == "__main__":
    main()
