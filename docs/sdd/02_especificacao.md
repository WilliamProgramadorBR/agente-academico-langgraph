# 2. Especificação (Spec)

## Requisitos funcionais

| ID | Requisito | Critério de aceite |
|---|---|---|
| RF01 | Responder dúvidas com RAG citando a fonte | Resposta contém `fontes` ⊆ evidências recuperadas; status `respondido` exige ≥1 fonte |
| RF02 | Consultar protocolo sem inventar estado | `consultar_protocolo` é chamada; status informado = status do SQLite; protocolo inexistente → `encontrado=false` |
| RF03 | Registrar solicitação só com intenção explícita e dados válidos | Sem verbo de pedido → bloqueio; campos obrigatórios por tipo (ACAD-005: turma + justificativa) validados; registro persistido em SQLite |
| RF04 | Abster-se sem evidência | Evidência abaixo de `RAG_SCORE_MIN` é descartada; resposta "respondido" sem fonte é convertida em `sem_evidencia` |
| RF05 | Impedir ações indevidas | "alterar nota/frequência" → `recusado` sem chamar LLM; Tool fora da allowlist → bloqueada |
| RF06 | Registrar decisões e Tools nos testes | Trace JSONL por atendimento + relatório por cenário |

## Requisitos técnicos (do enunciado)

| ID | Requisito | Critério de aceite |
|---|---|---|
| RT01 | Instruções do agente (fontes, autoridade, Tools, desconhecimento) | `SYSTEM_PROMPT` cobre as 4 dimensões |
| RT02 | Structured Output com contrato tipado | `RespostaAgente` (Pydantic) com resposta, fontes, status, protocolo |
| RT03 | Tratar falha de schema, mensagem vazia, erro de serviço, resultado inválido de Tool | Teste automatizado para cada caso |
| RT04 | Indexar ≥ 8 docs com ID e categoria em metadados | 12 docs, payload `fonte`, `categoria`, `titulo` |
| RT05 | Embeddings + busca vetorial com Top-K configurável | `RAG_TOP_K` e argumento `top_k` da Tool |
| RT06 | Compatibilidade ingestão × consulta | Índice grava `embedding_id`; consulta recusa modelo/dimensão diferente |
| RT07 | 3 Tools tipadas (conhecimento, consulta, ação) | `args_schema` Pydantic em todas |
| RT08 | Executar só Tools autorizadas, validando argumentos | Allowlist + validação Pydantic antes de executar |
| RT09 | StateGraph com estado explícito, nó agente, ToolNode/equivalente, roteamento condicional | `EstadoAgente`, `agente`, `executar_tools`, `add_conditional_edges` |
| RT10 | Nó real de validação além do ciclo agente↔Tools | `guardrail_entrada` e `validar_resposta` |
| RT11 | Limite de rodadas registrado em teste | `MAX_RODADAS` + `recursion_limit`; teste `test_limite_de_rodadas_encerra_loop` |
| RT12 | 10 cenários com passou/parcial/falhou e evidências | `executar_cenarios` + gabarito |
| RT13 | Logs sem tokens/chaves | `mascarar()` + teste |
| RT14 | Tratamento de 429/timeout | Retry com backoff + teste |

## Requisitos de medição (adicionados pela equipe)

| ID | Requisito | Critério de aceite |
|---|---|---|
| RM01 | Acurácia por LLM nos mesmos cenários | Ranking com acurácia estrita/ponderada, por dimensão e matriz cenário × modelo |
| RM02 | Qualidade do retrieval por modelo de embeddings | Hit@1, Hit@3, MRR, margem de separação e limiar sugerido |
| RM03 | Contabilizar erros por modelo | Tentativas bloqueadas, args inválidos, falhas de schema, correções, erros de serviço, latência |

## Contrato de saída

```json
{"resposta": "str", "fontes": ["ACAD-xxx"], "status": "respondido|sem_evidencia|protocolo_consultado|protocolo_nao_encontrado|solicitacao_registrada|aguardando_dados|recusado|erro",
 "protocolo": "SOL-xxxx|null", "tools_acionadas": ["..."], "rodadas": 0, "correcoes_validacao": ["..."],
 "origem_estrutura": "llm|deterministico|guardrail"}
```
