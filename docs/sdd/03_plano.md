# 3. Plano (Plan)

## Decisões de arquitetura

| # | Decisão | Alternativas consideradas | Motivo |
|---|---|---|---|
| D1 | Backend Python local, sem Docker (modalidade A/E) | Compose backend + Qdrant | Docker não pontua; menos peças para reproduzir |
| D2 | LLM configurável por `.env` (Ollama, Groq, Gemini, OpenRouter, OpenAI-compatível) | Fixar um provedor | Requisito da equipe: o usuário escolhe; a escolha é comparada por métricas |
| D3 | Qdrant embedded em disco; `QDRANT_URL` para servidor/cloud | Chroma, Pinecone | Mesmo código para local, Docker e cloud; sem conta |
| D4 | Embeddings `bge-m3` via Ollama | MiniLM (fastembed), nomic-embed-text | Medido: MRR 1,0 e margem +0,295 vs. margem negativa do MiniLM (ver `evidencias/metricas/retrieval_embeddings.md`) |
| D5 | Guardrails determinísticos antes do LLM (alterar nota, vazio) | Confiar só no prompt | Ação proibida não depende da obediência do modelo; zero custo de LLM |
| D6 | Executor de Tools próprio em vez do `ToolNode` pré-pronto | `ToolNode` | Precisa bloquear chamadas individualmente (allowlist, intenção, duplicidade) e validar o **resultado** — ainda devolvendo `ToolMessage` para cada `tool_call` |
| D7 | Structured Output em nó separado, com fallback determinístico | `response_format` direto no agente | Modelos pequenos falham no schema; o fallback garante o contrato e a falha fica registrada |
| D8 | Validação cruzada da saída com os resultados reais das Tools | Aceitar a saída do LLM | Remove fontes/protocolos inventados, corrige status, força abstenção |
| D9 | Limite duplo de loop: `MAX_RODADAS` no estado + `recursion_limit` do LangGraph | Só `recursion_limit` | O primeiro encerra com resposta controlada; o segundo é rede de segurança |
| D10 | Banco de protocolos novo por execução de avaliação | Banco compartilhado | Cenários reprodutíveis (SOL-1001 sempre `em_analise`; novo registro sempre SOL-1004) |
| D11 | Gabarito comportamental separado das perguntas | Avaliação manual | Perguntas do CSV ficam intactas; avaliação repetível entre modelos |
| D12 | Nó de controle `exigir_evidencia` (1 reenvio com instrução reforçada) | `tool_choice="required"`; pré-RAG obrigatório | Funciona em qualquer provedor (Ollama não suporta `tool_choice`) e preserva a decisão do agente; adicionado após a avaliação mostrar respostas sem consulta (T06/T07) |

## Fluxo do grafo

`START → guardrail_entrada → (bloqueado) validar_resposta → END`
`START → guardrail_entrada → agente ⇄ executar_tools … → validar_resposta → END`
`agente → exigir_evidencia → agente` (só se respondeu sem nenhuma Tool, no máximo 1 vez)

## Estado (`EstadoAgente`)

`messages` (add_messages), `pergunta`, `rodadas`, `bloqueio`, `sinais`, `erro`, `limite_atingido`,
`chamadas_llm`, `reforco_evidencia`, `eventos_tools` (acumulado), `resposta_final`.
