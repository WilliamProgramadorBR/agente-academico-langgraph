"""Gera o ZIP de entrega sem segredos, ambiente virtual, caches ou índices gerados.

Uso:  python empacotar_entrega.py            -> ../entrega/Projeto_Agente_Academico.zip
O script falha se encontrar algo parecido com chave de API nos arquivos incluídos.
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DESTINO = RAIZ.parent / "entrega" / "Projeto_Agente_Academico.zip"

EXCLUIR_DIRS = {".venv", "__pycache__", ".pytest_cache", ".git", "qdrant", "cache_modelos"}
EXCLUIR_ARQUIVOS = {".env"}
EXCLUIR_SUFIXOS = {".db", ".pyc", ".lock"}
SEGREDOS = re.compile(r"gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z\-_]{30,}|pcsk_[A-Za-z0-9_]{20,}")


def incluir(p: Path) -> bool:
    rel = p.relative_to(RAIZ)
    if any(parte in EXCLUIR_DIRS for parte in rel.parts):
        return False
    return p.name not in EXCLUIR_ARQUIVOS and p.suffix not in EXCLUIR_SUFIXOS


def main() -> None:
    arquivos = sorted(p for p in RAIZ.rglob("*") if p.is_file() and incluir(p))
    suspeitos = []
    for p in arquivos:
        if p.suffix in {".py", ".md", ".json", ".jsonl", ".txt", ".csv", ".example", ".ini", ".log"} or p.name.startswith("."):
            if SEGREDOS.search(p.read_text(encoding="utf-8", errors="ignore")):
                suspeitos.append(p.relative_to(RAIZ))
    if suspeitos:
        print("ABORTADO: possíveis chaves encontradas em:", *suspeitos, sep="\n  ")
        sys.exit(1)
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(DESTINO, "w", zipfile.ZIP_DEFLATED) as z:
        for p in arquivos:
            z.write(p, Path("projeto") / p.relative_to(RAIZ))
    print(f"{len(arquivos)} arquivos → {DESTINO} ({DESTINO.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
