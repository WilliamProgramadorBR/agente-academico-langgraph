"""Terminal interativo do Assistente Acadêmico.

Uso:  python -m agente.cli [--debug]
Comandos: /sair, /novo (nova conversa), /json (mostra a última resposta estruturada), /config
"""
from __future__ import annotations

import argparse
import json
import uuid

from .config import carregar_config
from .fabrica import montar_agente
from .observabilidade import Tracer


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--debug", action="store_true", help="mostra os eventos do trace no terminal")
    args = ap.parse_args()
    cfg = carregar_config()
    if args.debug:
        cfg.log_console = True
    print("Assistente Acadêmico — Instituto Horizonte (fictício)")
    print(f"LLM {cfg.llm_provider}:{cfg.llm_model} · embeddings {cfg.embedding_provider} · "
          "digite /sair para encerrar\n")
    agente = montar_agente(cfg)
    thread = uuid.uuid4().hex[:8]
    ultima = None
    while True:
        try:
            texto = input("Você: ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        cmd = texto.strip().lower()
        if cmd in {"/sair", "sair", "exit"}:
            break
        if cmd == "/novo":
            thread = uuid.uuid4().hex[:8]
            print("(nova conversa)\n")
            continue
        if cmd == "/json":
            print(json.dumps(ultima, ensure_ascii=False, indent=2) if ultima else "(nenhuma resposta ainda)", "\n")
            continue
        if cmd == "/config":
            print(json.dumps(cfg.resumo_seguro(), ensure_ascii=False, indent=2), "\n")
            continue
        tracer = Tracer(cfg.log_dir, console=cfg.log_console, rotulo=f"cli|{thread}")
        saida = agente.responder(texto, thread_id=thread, tracer=tracer)
        ultima = saida["resposta"]
        r = saida["resposta"]
        print(f"\nAssistente: {r['resposta']}")
        meta = [f"status={r['status']}"]
        if r["fontes"]:
            meta.append("fontes=" + ",".join(r["fontes"]))
        if r.get("protocolo"):
            meta.append(f"protocolo={r['protocolo']}")
        if r["tools_acionadas"]:
            meta.append("tools=" + ",".join(r["tools_acionadas"]))
        meta.append(f"{saida['latencia_s']}s")
        print(f"   [{' · '.join(meta)} · trace {saida['trace_id']}]\n")


if __name__ == "__main__":
    main()
