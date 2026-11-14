# Agente Acadêmico Inteligente — Instituto Horizonte (fictício)

Projeto Integrador · PEW1029 Aplicações Avançadas de IA · Turma 6001 · 2026.2

Agente de atendimento acadêmico que **responde dúvidas com RAG citando a fonte**, **consulta protocolos**,
**registra solicitações só com intenção explícita**, **se abstém sem evidência** e **recusa ações indevidas**
(como alterar nota). Construído com LangChain (Tools tipadas), LangGraph (StateGraph), Qdrant e Pydantic.

## Modo de execução escolhido

**Modalidade A/E — backend Python local, sem Docker.** Tudo roda na máquina do estudante:

| Componente | Escolha padrão | Alternativas (só mudar o `.env`) |
|---|---|---|
| LLM | Ollama local `qwen2.5:7b` | Groq, Gemini, OpenRouter, qualquer endpoint OpenAI-compatível |
| Embeddings | Ollama `bge-m3` (multilíngue) | fastembed (ONNX/CPU), Gemini embeddings |
| Vector store | Qdrant **embedded** em disco (`dados/qdrant`) | Qdrant em Docker ou Qdrant Cloud (`QDRANT_URL`) |
| Protocolos | SQLite (`dados/protocolos.db`) | — |
| Interface | CLI interativa no terminal | — |

Nenhum serviço pago, cartão ou GPU obrigatória. O provedor do LLM é **configurável pelo usuário** — a
comparação entre modelos está em [`evidencias/metricas/comparacao_llms.md`](evidencias/metricas/comparacao_llms.md).

## Arquitetura

```
                      ┌─────────────────────────────── LangGraph StateGraph ───────────────────────────────┐
 pergunta ──► guardrail_entrada ──(bloqueado: vazio / alterar nota)──────────────────────┐                    │
                      │ permitido                                                        ▼                    │
                      ▼                    (resposta final / erro / limite)      validar_resposta ──► resposta│
                   agente  ───────────────────────────────────────────────────►  (Structured Output         │
               (LLM + Tools)                                                      Pydantic + checagens)      │
                   ▲   │ tool_calls                                                                          │
                   │   ▼                                                                                     │
               executar_tools: allowlist · intenção explícita p/ ação · validação de args · validação do      │
                               resultado · log                                                              │
   agente ──(respondeu sem consultar nenhuma Tool, 1ª vez)──► exigir_evidencia ──► agente (instrução reforçada)│
                      └──────────────────────────────────────────────────────────────────────────────────────┘
   buscar_normas ──► Qdrant (embeddings)      consultar_protocolo ──► SQLite (leitura)
   registrar_solicitacao ──► SQLite (escrita)
```

| Requisito | Onde está |
|---|---|
| Instruções do agente (fontes, autoridade, Tools, abstenção) | [agente/prompts.py](agente/prompts.py) |
| Contratos tipados (args, resultados, resposta final) | [agente/schemas.py](agente/schemas.py) |
| Ingestão (12 docs, `fonte` e `categoria` em metadados) | [agente/vetores.py](agente/vetores.py), [agente/indexar.py](agente/indexar.py) |
| Compatibilidade ingestão × consulta (modelo/dimensão) | `Recuperador._verificar_compatibilidade` em [agente/vetores.py](agente/vetores.py) |
| 3 Tools tipadas (conhecimento, consulta, ação) | [agente/tools.py](agente/tools.py) |
| StateGraph, roteamento, nós de controle/validação, limite de rodadas | [agente/grafo.py](agente/grafo.py) |
| Guardrails determinísticos (alterar nota, injeção, intenção) | [agente/guardrails.py](agente/guardrails.py) |
| 429 / timeout / indisponibilidade (retry com backoff) | [agente/llm.py](agente/llm.py) |
| Trace JSONL com mascaramento de segredos | [agente/observabilidade.py](agente/observabilidade.py) |
| Execução e avaliação dos 10 cenários | [agente/executar_cenarios.py](agente/executar_cenarios.py), [agente/avaliacao.py](agente/avaliacao.py), [dados/gabarito_cenarios.json](dados/gabarito_cenarios.json) |
| Comparação de LLMs e de embeddings | [agente/comparar_modelos.py](agente/comparar_modelos.py), [agente/avaliar_retrieval.py](agente/avaliar_retrieval.py) |
| Testes offline (mocks) | [tests/](tests/) |

## Como executar (Windows / PowerShell — Linux/macOS entre parênteses)

Pré-requisitos: Python 3.11 ou 3.12 e [Ollama](https://ollama.com/download) (só se usar modelos locais).

```powershell
# 1. ambiente virtual e dependências
py -3.12 -m venv .venv                      # (python3 -m venv .venv)
.\.venv\Scripts\Activate.ps1                # (source .venv/bin/activate)
pip install -r requirements.txt

# 2. configuração
copy .env.example .env                      # (cp .env.example .env)  — edite provedor/modelo/chaves

# 3. modelos locais (pule se usar LLM/embeddings em cloud)
ollama pull qwen2.5:7b
ollama pull bge-m3

# 4. indexar a base (12 documentos) e testar uma busca
python -m agente.indexar --testar "frequência mínima para certificação"

# 5. conversar com o agente
python -m agente.cli                        # --debug mostra o trace no terminal

# 6. executar os 10 cenários e gerar evidências
python -m agente.executar_cenarios          # --repeticoes 3 para medir variância

# 7. métricas: comparar embeddings e comparar LLMs
python -m agente.avaliar_retrieval
python -m agente.comparar_modelos           # --apenas "qwen2.5-7b,groq" --repeticoes 3

# 8. testes offline (sem LLM real: limite de rodadas, 429, schema, Tools)
python -m pytest -q

# 9. gerar o ZIP de entrega (sem .env, venv, caches; aborta se achar chave de API)
python empacotar_entrega.py
```

> O Qdrant embedded aceita **um processo por vez**: não rode a CLI e os cenários ao mesmo tempo
> (ou use `QDRANT_URL` com um servidor Qdrant).

Para usar um LLM em cloud basta trocar no `.env`, por exemplo `LLM_PROVIDER=groq`,
`LLM_MODEL=llama-3.3-70b-versatile`, `LLM_API_KEY=...`. Para incluí-lo na comparação, preencha
`GROQ_API_KEY` (ou `GEMINI_API_KEY`, `OPENROUTER_API_KEY`) — os modelos ficam em
[dados/modelos_avaliacao.json](dados/modelos_avaliacao.json).

**Trocou o modelo de embeddings? Rode `python -m agente.indexar` de novo.** A consulta recusa um índice
criado com outro modelo/dimensão em vez de devolver resultados sem sentido.

## Serviços externos

Nenhum é obrigatório na configuração padrão. Opcionais: Groq, Google AI Studio (Gemini), OpenRouter, Qdrant Cloud.
Chaves ficam apenas no `.env` (fora do controle de versão); os logs mascaram chaves, tokens, senhas e CPF.

## Evidências e relatório

- [docs/RELATORIO.md](docs/RELATORIO.md) — relatório dos 10 cenários, métricas, análise de falhas, uso de IA
- [evidencias/execucoes/](evidencias/execucoes/) — por execução: `relatorio.md` + `resultados.json`
- [evidencias/metricas/](evidencias/metricas/) — comparação de LLMs e de embeddings (MD, JSON, CSV)
- [evidencias/logs/](evidencias/logs/) — trace JSONL (decisões, Tools, argumentos, resultados, erros, término)
- [docs/sdd/](docs/sdd/) — Spec-Driven Development (Intent → Spec → Plan → Tasks → Validate)
