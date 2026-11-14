# 1. Intenção (Intent)

**Problema.** O Instituto Horizonte (fictício) precisa de um agente de atendimento acadêmico confiável: que
responda com base nos documentos oficiais, diga de onde tirou a resposta, consulte e registre protocolos, e que
**não invente** nem execute ações fora da sua autoridade.

**Para quem.** Estudantes (usuários finais) e a equipe de atendimento (que audita o que o agente fez).

**Resultado desejado.**
1. Respostas corretas e citadas para dúvidas cobertas pela base (12 documentos ACAD-001 a ACAD-012).
2. Status de protocolo sempre vindo do sistema, nunca suposto.
3. Novas solicitações registradas só quando o estudante pede, e com os dados exigidos pela norma.
4. Abstenção explícita quando a base não cobre o assunto; recusa quando o pedido extrapola a autoridade.
5. Todo atendimento auditável: decisões, Tools, argumentos, resultados, erros e término registrados, sem segredos.
6. Liberdade de provedor: o usuário escolhe o LLM; a qualidade de cada escolha é **medida**, não presumida.

**Fora de escopo.** Interface gráfica, API HTTP pública, autenticação real de estudantes, dados reais.

**Riscos principais.** Alucinação de prazos/valores; prompt injection ("ignore as políticas"); ação indevida
(registrar sem pedido, alterar nota); loops de Tool; cotas/429 de free tier; modelos pequenos com Tool Calling
instável.
