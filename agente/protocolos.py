"""Sistema simulado de solicitações/protocolos (SQLite).

Na primeira execução é criado com protocolos fictícios de exemplo
(SOL-1001 a SOL-1003). Novos registros recebem numeração sequencial.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

PROTOCOLOS_INICIAIS = [
    ("SOL-1001", "declaracao_matricula", "em_analise",
     "Declaração de matrícula solicitada; portal apresentou falha na emissão.", "6001",
     "2026-11-03T10:15:00", "2026-11-05T14:20:00"),
    ("SOL-1002", "suporte_plataforma", "concluida",
     "Erro ao abrir videoaula da disciplina de LangGraph.", "6001",
     "2026-10-20T09:00:00", "2026-10-22T16:45:00"),
    ("SOL-1003", "segunda_via_certificado", "aguardando_documentos",
     "Segunda via do certificado do módulo 1.", "5002",
     "2026-10-28T11:30:00", "2026-10-30T08:10:00"),
]


class RepositorioProtocolos:
    def __init__(self, caminho: str):
        self.caminho = caminho
        Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        self._inicializar()

    @contextmanager
    def _conn(self):
        """Abre conexão, faz commit/rollback e sempre fecha (evita lock no Windows)."""
        conn = sqlite3.connect(self.caminho, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _inicializar(self) -> None:
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS solicitacoes (
                       protocolo TEXT PRIMARY KEY,
                       tipo TEXT NOT NULL,
                       status TEXT NOT NULL,
                       descricao TEXT NOT NULL,
                       turma TEXT,
                       disciplina TEXT,
                       justificativa TEXT,
                       criado_em TEXT NOT NULL,
                       atualizado_em TEXT NOT NULL,
                       origem TEXT NOT NULL DEFAULT 'seed'
                   )"""
            )
            if c.execute("SELECT COUNT(*) FROM solicitacoes").fetchone()[0] == 0:
                c.executemany(
                    "INSERT INTO solicitacoes (protocolo, tipo, status, descricao, turma, criado_em, atualizado_em)"
                    " VALUES (?,?,?,?,?,?,?)",
                    PROTOCOLOS_INICIAIS,
                )

    def consultar(self, protocolo: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM solicitacoes WHERE protocolo = ?", (protocolo,)).fetchone()
        return dict(row) if row else None

    def registrar(self, tipo: str, descricao: str, turma: str | None = None,
                  disciplina: str | None = None, justificativa: str | None = None) -> dict:
        agora = datetime.now().isoformat(timespec="seconds")
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            ultimo = c.execute(
                "SELECT MAX(CAST(SUBSTR(protocolo, 5) AS INTEGER)) FROM solicitacoes"
            ).fetchone()[0] or 1000
            protocolo = f"SOL-{ultimo + 1}"
            c.execute(
                "INSERT INTO solicitacoes VALUES (?,?,?,?,?,?,?,?,?,?)",
                (protocolo, tipo, "aberta", descricao, turma, disciplina, justificativa, agora, agora, "agente"),
            )
        return self.consultar(protocolo)
