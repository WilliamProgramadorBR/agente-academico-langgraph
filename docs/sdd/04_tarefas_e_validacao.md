# 4. Tarefas (Tasks) e 5. Implementação / Teste / Validação

## Tarefas

| Tarefa | Requisitos | Implementação | Status |
|---|---|---|---|
| T-01 Configuração por `.env` sem vazar segredos | D2, RT13 | `agente/config.py` (`resumo_seguro`) | ✅ |
| T-02 Ingestão + compatibilidade de embeddings | RT04–RT06 | `agente/vetores.py`, `agente/indexar.py` | ✅ |
| T-03 Contratos Pydantic | RT02, RT07 | `agente/schemas.py` | ✅ |
| T-04 Tools tipadas + SQLite | RF02, RF03, RT07 | `agente/tools.py`, `agente/protocolos.py` | ✅ |
| T-05 Prompt do agente | RT01 | `agente/prompts.py` | ✅ |
| T-06 Guardrails de entrada e de intenção | RF05, RF03 | `agente/guardrails.py` | ✅ |
| T-07 StateGraph + executor de Tools + validação | RT08–RT11, RF01, RF04 | `agente/grafo.py` | ✅ |
| T-08 Retry 429/timeout | RT14 | `agente/llm.py` | ✅ |
| T-09 Trace JSONL mascarado | RF06, RT13 | `agente/observabilidade.py` | ✅ |
| T-10 Testes offline (mocks) | RT03, RT11, RT13, RT14 | `tests/` | ✅ |
| T-11 Execução dos 10 cenários + gabarito | RT12 | `agente/executar_cenarios.py`, `agente/avaliacao.py`, `dados/gabarito_cenarios.json` | ✅ |
| T-12 Métricas de embeddings | RM02 | `agente/avaliar_retrieval.py` | ✅ |
| T-13 Comparação de LLMs | RM01, RM03 | `agente/comparar_modelos.py` | ✅ |
| T-14 Correções guiadas pela avaliação (6 falhas → 6 testes de regressão) | RF01–RF05 | ver `docs/RELATORIO.md` §4.2 | ✅ |
| T-15 Empacotamento sem segredos | RT13 | `empacotar_entrega.py` | ✅ |

## Matriz de rastreabilidade (requisito → teste → evidência)

| Requisito | Teste automatizado (offline) | Evidência real (LLM) |
|---|---|---|
| RF01 citar fonte | `test_falha_de_schema_usa_fallback_deterministico`, `test_fonte_inventada_e_protocolo_inventado_sao_removidos` | T01, T02, T03, T06, T07, T08 |
| RF02 protocolo | `test_consulta_protocolo_inexistente` | T04 |
| RF03 registro com intenção + dados | `test_registro_sem_intencao_explicita_bloqueado`, `test_registro_com_dados_faltando_depois_completo`, `test_registro_rejeita_turma_generica_e_exige_justificativa` | T05 (2 turnos), T07/T08 sem registro |
| RF04 abstenção | `test_resposta_sem_evidencia_vira_abstencao` | T09 |
| RF05 ação indevida | `test_guardrail_recusa_alterar_nota_sem_chamar_llm`, `test_tool_nao_autorizada_bloqueada`, `test_acao_proibida_bloqueada` | T10 |
| RT03 schema / vazio / serviço / Tool | `test_falha_de_schema...`, `test_mensagem_vazia...`, `test_resposta_vazia_do_llm`, `test_429_persistente...`, `test_resultado_invalido_de_tool` | contadores na comparação de LLMs |
| RT06 compatibilidade | `Recuperador._verificar_compatibilidade` (falha explícita ao trocar modelo) | `indexar` registra `embedding_id` |
| RT11 limite de rodadas | `test_limite_de_rodadas_encerra_loop` | coluna "Limite de rodadas" |
| RT13 mascaramento | `test_mascaramento_de_segredos` | `evidencias/logs/*.jsonl` |
| RT14 429/timeout | `test_429_com_retry_e_sucesso`, `test_429_persistente_vira_erro_controlado`, `test_timeout_classificado` | coluna "Erros serviço LLM" |
| RM01–RM03 | — | `evidencias/metricas/comparacao_llms.md`, `retrieval_embeddings.md` |

Execução: `python -m pytest -q` → 36 testes passando (`evidencias/testes_offline.txt`).
