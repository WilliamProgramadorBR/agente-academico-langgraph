# Comparação de embeddings (retrieval)

Gerado em 14/11/2026 12:04. Top-K = 3. Positivos: T01, T02, T03, T05, T06, T07, T08 (documento relevante conhecido). Negativo: T09 (a base não tem a resposta).

| # | Modelo | Hit@1 | Hit@3 | MRR | Score médio relevante | Maior score T09 | Margem | Limiar sugerido | Busca (ms) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | bge-m3 (Ollama) | 1.00 | 1.00 | 1.000 | 0.695 | 0.289 | +0.295 | 0.436 | 45.0 |
| 2 | MiniLM-L12 multilingue (fastembed) | 0.86 | 1.00 | 0.905 | 0.624 | 0.343 | -0.005 | — | 6.4 |
| 3 | nomic-embed-text (Ollama) | 0.71 | 1.00 | 0.857 | 0.789 | 0.630 | +0.033 | 0.646 | 20.6 |

Margem = menor score do documento correto − maior score obtido na pergunta sem resposta. Margem positiva significa que existe um limiar que separa evidência real de ruído.

## Ranking por pergunta (top-3)

### bge-m3 (Ollama)
- T01 [positivo]: ACAD-001 (0.75), ACAD-005 (0.47), ACAD-004 (0.44) — relevante na posição 1
- T02 [positivo]: ACAD-002 (0.69), ACAD-005 (0.49), ACAD-010 (0.42) — relevante na posição 1
- T03 [positivo]: ACAD-003 (0.74), ACAD-005 (0.56), ACAD-008 (0.54) — relevante na posição 1
- T05 [positivo]: ACAD-005 (0.74), ACAD-002 (0.57), ACAD-010 (0.56) — relevante na posição 1
- T06 [positivo]: ACAD-006 (0.64), ACAD-007 (0.52), ACAD-010 (0.49) — relevante na posição 1
- T07 [positivo]: ACAD-007 (0.73), ACAD-010 (0.49), ACAD-006 (0.44) — relevante na posição 1
- T08 [positivo]: ACAD-008 (0.58), ACAD-001 (0.52), ACAD-002 (0.40) — relevante na posição 1
- T09 [negativo (sem resposta na base)]: ACAD-003 (0.29), ACAD-002 (0.29), ACAD-005 (0.27)

### MiniLM-L12 multilingue (fastembed)
- T01 [positivo]: ACAD-001 (0.72), ACAD-005 (0.44), ACAD-002 (0.41) — relevante na posição 1
- T02 [positivo]: ACAD-002 (0.70), ACAD-005 (0.47), ACAD-001 (0.46) — relevante na posição 1
- T03 [positivo]: ACAD-003 (0.68), ACAD-001 (0.37), ACAD-008 (0.33) — relevante na posição 1
- T05 [positivo]: ACAD-005 (0.77), ACAD-001 (0.54), ACAD-002 (0.50) — relevante na posição 1
- T06 [positivo]: ACAD-006 (0.55), ACAD-011 (0.49), ACAD-009 (0.48) — relevante na posição 1
- T07 [positivo]: ACAD-007 (0.61), ACAD-001 (0.25), ACAD-012 (0.24) — relevante na posição 1
- T08 [positivo]: ACAD-005 (0.35), ACAD-006 (0.34), ACAD-008 (0.34) — relevante na posição 3
- T09 [negativo (sem resposta na base)]: ACAD-001 (0.34), ACAD-003 (0.34), ACAD-005 (0.30)

### nomic-embed-text (Ollama)
- T01 [positivo]: ACAD-001 (0.85), ACAD-002 (0.73), ACAD-005 (0.71) — relevante na posição 1
- T02 [positivo]: ACAD-002 (0.89), ACAD-005 (0.67), ACAD-001 (0.63) — relevante na posição 1
- T03 [positivo]: ACAD-003 (0.80), ACAD-011 (0.65), ACAD-001 (0.62) — relevante na posição 1
- T05 [positivo]: ACAD-005 (0.82), ACAD-001 (0.68), ACAD-002 (0.66) — relevante na posição 1
- T06 [positivo]: ACAD-011 (0.70), ACAD-006 (0.70), ACAD-001 (0.68) — relevante na posição 2
- T07 [positivo]: ACAD-007 (0.81), ACAD-009 (0.67), ACAD-006 (0.66) — relevante na posição 1
- T08 [positivo]: ACAD-001 (0.72), ACAD-008 (0.66), ACAD-002 (0.63) — relevante na posição 2
- T09 [negativo (sem resposta na base)]: ACAD-010 (0.63), ACAD-007 (0.61), ACAD-003 (0.61)
