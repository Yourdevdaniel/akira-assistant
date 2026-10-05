# Assistente Pessoal — Spec Técnica (v0.2)

> **Nota de publicação:** este é o rascunho de desenho original, anterior ao código. O sistema implementado divergiu em vários pontos: roda sobre o OpenJarvis, conversa pelo Telegram (sem app desktop ou Android) e usa `llama3.2:3b` com um classificador em JSON travado em vez de tool calling livre. O README descreve o que existe hoje.

> Status: rascunho. Substitui a v0.1 — o hardware foi medido e várias decisões mudaram.
> Data: 2026-09-21 · Nome do projeto: a definir

---

## 1. Visão

Assistente pessoal local, em português do Brasil, que conversa por texto e por voz
(modo ligação), gerencia agenda, tarefas, notas e email, e — o diferencial — **toma
iniciativa**: monitora o que importa e te chama quando algo precisa de você.

Roda 100% com IA local. Sem custo por token, sem enviar dado pessoal pra fora.

---

## 2. Restrições reais (medidas, não estimadas)

| Recurso | Valor | Implicação |
|---|---|---|
| GPU | GTX 1660 SUPER, 6GB VRAM, Turing 7.5 | Gargalo principal. ~1,4GB já ocupado pelo desktop |
| Banda VRAM | ~336 GB/s | Define a velocidade do LLM na GPU |
| CPU | Xeon E5-2650 v3, 10c/20t @2.3GHz | Lento por core, mas 20 threads disponíveis |
| RAM | 16GB DDR4-2133, **2 de 4 canais** | Banda ~25 GB/s real. Ver §9 (upgrade) |
| Placa-mãe | Machinist E5-RS9 (X99), 4 slots, máx 128GB | Espaço pra dobrar banda de memória |
| Disco | 260GB livres | Sem restrição |
| Uptime | **Máquina não fica 24/7** | Restrição forte no módulo proativo (§5.4) |

**Consequência central:** o modo ligação precisa dos três modelos (STT, LLM, TTS) vivos ao
mesmo tempo. Em 6GB de VRAM, isso só fecha com uma alocação deliberada:

```
GPU (6GB)   → exclusivamente o LLM. Nada mais.
CPU (20t)   → Whisper (STT) + Kokoro (TTS). Ambos leves, nenhum precisa de GPU.
```

Isso não é workaround. Whisper `small` int8 e Kokoro (82M params) são compute-bound,
não bandwidth-bound: 20 threads dão conta. Colocá-los na GPU roubaria VRAM do LLM, que
é quem realmente sofre com falta dela.

---

## 3. Escopo

### v1 — Assistente de texto (4-6 semanas)
- [ ] Chat de texto com Qwen local (Ollama)
- [ ] Tool calling confiável em PT-BR (ver §5.1 — é o risco #1)
- [ ] Notas próprias: CRUD + busca full-text
- [ ] Tarefas: CRUD, prazo, prioridade, vínculo com nota/evento
- [ ] Calendário: CRUD via Google Calendar
- [ ] App desktop Windows (Tauri 2) — PC e notebook
- [ ] Log completo de toda interação (§5.9)

### v1.5 — Voz / Modo Ligação (3-5 semanas)
- [ ] Pipeline de voz em streaming, ponta a ponta
- [ ] Vocabulário pessoal (§5.3) — nomes próprios em PT-BR
- [ ] Barge-in (interromper o assistente falando)
- [ ] Tela de chamada no cliente

### v2 — Proatividade (3-4 semanas)
- [ ] Monitores: agenda, email, tarefas, rotina
- [ ] Régua de interrupção (§5.4) — a parte difícil
- [ ] Ligação de saída dentro do app + push
- [ ] Catch-up ao ligar a máquina

### v2.5 — App Android
- [ ] App Android (React Native + Expo), chat e leitura offline
- [ ] Push nativo (FCM) pros alertas da régua de interrupção

### v3 — Email
- [ ] Email: ler, resumir, rascunhar (com o modelo de segurança do §5.9)

### v4 — Telefonia real
- [ ] Ligação no número de verdade (Twilio), pra alcançar você com o app fechado

### Fora de escopo
- Fine-tuning · Multiusuário · Deploy externo com GPU na nuvem

---

## 4. Decisões de arquitetura

| Decisão | Escolha | Trade-off aceito |
|---|---|---|
| LLM (voz) | **qwen3:4b** Q4 na GPU (~2,7GB) | Menos capaz que o 8b; ganha latência, que é inegociável em ligação |
| LLM (texto) | **qwen3:8b** Q4 na GPU (~5,2GB) | Cabe sozinho. 2s de espera em chat é aceitável |
| Roteamento | Por modo (voz vs texto), não por heurística | Simples e previsível. Custa um swap de modelo ao alternar |
| Runtime LLM | Ollama (já instalado) | Se precisar de offload fino de MoE (§9), migra pra llama.cpp direto |
| STT | faster-whisper `small` int8, **CPU** | ~0,4s por 5s de fala. Libera a VRAM inteira pro LLM |
| TTS | Kokoro (voz pt-BR), **CPU** | 82M params, primeiro chunk em ~0,3s. Qualidade pt-BR a validar |
| Banco | **SQLite** + FTS5 | Um usuário, um processo. Postgres seria um container sem retorno |
| Busca de notas | FTS5 na v1; sqlite-vec quando FTS falhar | Adia embeddings até doer. Gatilho: busca por sinônimo falhando |
| Backend | FastAPI, **Python 3.12** (não 3.14) | 3.14 é novo demais pro stack de ML — ver §10, risco R4 |
| Transporte | WebSocket (voz) + REST (resto) | WS é obrigatório pra streaming bidirecional |
| Cliente desktop | **Tauri 2** (Rust + React) — Windows | `.exe` de ~8MB usando o WebView2 do SO. Não é Electron (não embute Chromium) nem site (não tem navegador). UI desenhada em HTML |
| Cliente mobile | **React Native + Expo** — Android | Widget nativo de verdade. Stack que já uso em outros projetos |
| Compartilhado | TypeScript: tipos da API, cliente HTTP/WS, lógica | A camada de UI **não** é compartilhada (RN usa `View`/`Text`, Tauri usa `div`). Aceito: duas UIs, uma linguagem |
| Rede | Tailscale | Mobile alcança o desktop de qualquer lugar, sem abrir porta |
| Auth | Token único no header | Um usuário, rede privada. Mais que isso é cerimônia |
| Calendário / Email | Google Calendar API + Gmail API | Um OAuth cobre os dois. Ver §10, risco R5 |

### Decisões da v0.1 que caíram
- ~~Postgres~~ → SQLite (um usuário, sem rede)
- ~~Flutter~~ → Tauri 2 + React Native. Flutter daria um codebase só, mas custa aprender
  Dart e sair do ecossistema React que já está em produção em 4 projetos seus. Duas
  camadas de UI em TypeScript sai mais barato que uma em linguagem nova
- ~~Cliente web / PWA~~ → aplicativo instalado nos dois lados (§12)
- ~~Piper/Coqui~~ → Kokoro (melhor, e tem voz pt-BR)
- ~~Backend do zero pra tudo~~ → ver §11 sobre o OpenJarvis

---

## 5. Módulos

### 5.1 Orquestrador — e o risco #1 do projeto

O backend expõe ferramentas que o Qwen chama:
`criar_evento`, `listar_eventos`, `editar_evento`, `criar_tarefa`, `concluir_tarefa`,
`listar_tarefas`, `criar_nota`, `buscar_notas`, `resumir_email`, `rascunhar_email`.

**Tudo depende de uma coisa não verificada:** o Qwen local acerta a ferramenta *e os
argumentos* em português? O modo de falha é traiçoeiro — ele chama a função certa com a
data errada. Marca a reunião. Na quinta errada.

Mitigações obrigatórias, desde o primeiro dia:

1. **Data de hoje + timezone no system prompt.** O modelo não sabe que dia é hoje.
   Sem isso, "quinta" é chute. Metade das falhas de tool calling vem daqui.
2. **Resolução de data fora do LLM.** "quinta às 15h" passa por um parser determinístico
   (dateparser em pt-BR) *antes* do modelo. O LLM decide a intenção; o código decide a data.
3. **Confirmação visível.** Toda ação que escreve mostra os argumentos antes de executar.
4. **Suite de regressão.** 40 frases reais em PT-BR × as 10 ferramentas, rodando no CI.
   Essa é a fitness function do projeto: se a taxa cair, você sabe no mesmo dia.

> **Tarefa zero, antes de qualquer arquitetura:** rodar essa suite contra `qwen3:4b` e
> `qwen3:8b`. Se o 4b ficar abaixo de 90%, o modo ligação muda de plano (ver §9).

### 5.2 Voz — Modo Ligação

Pipeline, todo em streaming:

```
mic → VAD → chunks → Whisper (CPU) → texto parcial
                                        ↓
                            LLM (GPU, streaming de tokens)
                                        ↓
                    frase completa? → Kokoro (CPU) → chunk de áudio → toca
```

A regra que faz tudo funcionar: **o TTS começa a falar na primeira frase pronta**, não na
resposta inteira. Sem isso a latência quadruplica e a sensação de conversa morre.

**Orçamento de latência** (fim da sua fala → primeiro áudio de volta):

| Etapa | Alvo |
|---|---|
| VAD detecta fim de fala | 200ms |
| Whisper transcreve o final | 250ms |
| LLM primeiro token | 300ms |
| LLM até a primeira frase (~15 tokens @35 tok/s) | 400ms |
| Kokoro primeiro chunk | 250ms |
| **Total** | **~1,2s** |

1,2s não é o 800ms de uma conversa humana, mas é conversável. Sem streaming seria 4-6s,
que é inutilizável. **Por isso streaming não é otimização, é requisito de arquitetura** —
retrofit em cima de request/response é reescrita.

**Barge-in** entra na v1.5, não na v2: em cima de streaming custa uma tarde (VAD ativo
durante a fala do TTS → cancela o playback e o stream do LLM). Mas só é barato porque a
arquitetura já nasceu em streaming.

### 5.3 Vocabulário pessoal — nomes próprios em PT-BR

Whisper erra nome próprio brasileiro com frequência alta. É o incômodo diário previsível
deste projeto, e tem solução concreta:

1. Tabela `vocabulario` populada automaticamente de: contatos, participantes de eventos,
   nomes que aparecem em notas, e termos que você corrigir manualmente.
2. Os N termos mais frequentes entram como `initial_prompt` do faster-whisper — isso
   enviesa o decoder na direção certa.
3. Pós-correção: tokens transcritos passam por fuzzy match contra o vocabulário.
   "Aquira" → "Akira" com distância 2 e confiança alta → corrige e registra.
4. Toda correção manual realimenta a tabela.

### 5.4 Proatividade — o módulo que te liga

O difícil aqui **não é a ligação**. É decidir que algo merece te interromper. Um
assistente que liga demais é desinstalado na primeira semana.

**Monitores:**

| Monitor | Observa |
|---|---|
| Agenda | Reunião chegando, conflito de horário, evento sem local, dia sobrecarregado |
| Email | Mensagem importante sem resposta, cobrança, prazo mencionado, remetente prioritário |
| Tarefas | Vencendo, prazo estourado, parada há dias, dia sem nada planejado |
| Rotina | Briefing da manhã, fechamento do dia, lembretes recorrentes |

**Régua de interrupção** — todo evento detectado é classificado em três níveis:

| Nível | Critério | Ação |
|---|---|---|
| 3 — Liga | Urgente **e** acionável agora **e** você provavelmente não sabe | Chamada |
| 2 — Avisa | Importante, mas não urgente | Push |
| 1 — Guarda | O resto | Entra no próximo briefing |

Os três critérios do nível 3 são **conjuntivos**. "Urgente mas você já sabe" não é
ligação — é ruído. Essa conjunção é o que separa assistente de alarme.

**Orçamento de interrupção:** máximo de ligações por dia (default: 3), janela de silêncio
configurável, e um botão "não era importante" em toda chamada. Esse feedback ajusta o
threshold por tipo de monitor. Sem orçamento, a régua degrada sozinha.

**A restrição do uptime.** A máquina não fica ligada 24/7. Consequência honesta:
*ele não vai te ligar às 7h se o PC estiver desligado.* Não tem como contornar isso
localmente — a GPU está nessa máquina.

O que dá pra fazer bem:

- **Catch-up na subida:** ao ligar, o scheduler roda os checks pendentes e aplica um
  filtro de relevância temporal. Alerta de reunião que já passou não vira ligação, vira
  linha no resumo. Alerta ainda válido é reclassificado pela régua normal.
- **Gatilho pro próximo degrau:** se a perda de alertas incomodar de verdade, um
  componente always-on mínimo (VPS de US$5 ou um Raspberry Pi) roda *só* o scheduler e o
  push — sem GPU, sem LLM — e delega o raciocínio pro desktop quando ele estiver de pé.
  **Isso é v3+, e só se doer.** Registrado aqui pra não virar improviso depois.

### 5.5 Calendário

CRUD via Google Calendar API. Linguagem natural → intenção pelo LLM, **data pelo parser
determinístico** (§5.1). Leitura pode ser direta; escrita passa por confirmação.

### 5.6 Tarefas

SQLite próprio (não Google Tasks — você quer campos seus).
Campos: `titulo`, `descricao`, `prazo`, `status`, `prioridade`, `nota_id?`, `evento_id?`,
`criada_em`, `atualizada_em`.

### 5.7 Notas

SQLite + FTS5 com tokenizer unicode61 e remoção de acentos — obrigatório pra PT-BR, senão
"reunião" não acha "reuniao". Vínculo opcional com tarefa e evento.
Busca semântica (sqlite-vec) fica pra quando a FTS falhar de verdade, não antes.

### 5.8 Email

Gmail API (mesmo OAuth do Calendar). Ler, resumir, rascunhar. **Nunca enviar sem
confirmação explícita.** Ver §5.9 — este é o módulo mais perigoso do sistema.

### 5.9 Segurança e observabilidade

**Prompt injection via email é a ameaça real deste projeto.** Você vai dar a um LLM acesso
de leitura ao seu email e capacidade de executar ferramentas. Qualquer pessoa que te mande
um email está escrevendo no prompt do seu assistente. Rodar local não protege contra isso —
protege contra vazamento pro provedor, que é outro problema.

Modelo mínimo, desde a v1 (mesmo antes do email existir):

1. **Marcação de confiança (taint).** Todo conteúdo externo — email, web, arquivo — entra
   no contexto marcado como dado, nunca como instrução, e cercado por delimitador.
2. **Separação de poder.** A sessão que *lê* conteúdo externo não tem acesso às ferramentas
   de escrita. Resumir e agir são dois turnos, com confirmação humana no meio.
3. **Confirmação de ação externa ou destrutiva** com os argumentos visíveis. Isso também
   pega o modelo errando argumento, que é o modo de falha mais provável (§5.1).

**Log de toda interação:** entrada, contexto, ferramenta escolhida, argumentos, resultado,
latência por etapa. Quando ele marcar a reunião no dia errado, é esse log que diz por quê.
Sem isso, "ele fez besteira" não tem diagnóstico.

---

## 6. Arquitetura

```
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│  PC (Tauri)   │  │ Note (Tauri)  │  │ Android (RN)  │   ← /shared em TypeScript
│   .exe 8MB    │  │   .exe 8MB    │  │  .apk nativo  │
└───────┬───────┘  └───────┬───────┘  └───────┬───────┘
        └─────────  WS (voz) + REST  ─────────┘
                          │  (Tailscale)
                 ┌────────▼─────────┐
                 │ Backend FastAPI  │
                 │ ┌──────────────┐ │
                 │ │ Orquestrador │ │  ← tool calling + roteamento de modelo
                 │ ├──────────────┤ │
                 │ │  Scheduler   │ │  ← monitores + régua de interrupção
                 │ ├──────────────┤ │
                 │ │  Segurança   │ │  ← taint, confirmação, log
                 │ └──────────────┘ │
                 └────────┬─────────┘
          ┌───────────────┼───────────────┬──────────────┐
    ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐  ┌─────▼─────┐
    │  Ollama   │   │  Whisper  │   │  Kokoro   │  │  SQLite   │
    │  GPU 6GB  │   │    CPU    │   │    CPU    │  │  + FTS5   │
    └───────────┘   └───────────┘   └───────────┘  └───────────┘
          │
          ▼ tool calling
    ┌──────────────────────────────┐
    │ Google Calendar · Gmail API  │
    └──────────────────────────────┘
```

---

## 7. Estrutura de repositório

```
/backend
  /orquestrador    → tool calling, roteamento, prompts
  /voz             → STT, TTS, VAD, streaming, vocabulário
  /proativo        → monitores, régua, scheduler
  /dominio         → notas, tarefas, calendário, email
  /seguranca       → taint, confirmação, auditoria
  /dados           → SQLite, migrations
/app-desktop       → Tauri 2 (Rust + React) — Windows
/app-mobile        → React Native + Expo — Android
/shared            → TypeScript: tipos da API, cliente HTTP/WS, lógica de domínio
/evals             → suite de regressão de tool calling PT-BR
/docs
  SPEC.md
  /adr
```

Regra de fronteira: `dominio` não importa `orquestrador`. Verificada por import-linter no CI.

---

## 8. Orçamento de VRAM

| Cenário | GPU | CPU/RAM | Cabe? |
|---|---|---|---|
| Chat de texto | qwen3:8b (5,2GB) | — | Apertado, cabe |
| Modo ligação | qwen3:4b (2,7GB) + contexto | Whisper 0,3GB + Kokoro 0,2GB | Confortável |
| Ligação com 8b | 5,2GB + contexto | idem | **Não** — estoura com o 1,4GB do desktop |

---

## 9. CPU e RAM — por que o LLM não mora ali (e quando poderia)

Pergunta legítima: por que não usar os 16GB de RAM e as 20 threads pro modelo?

**A física:** gerar um token num modelo denso exige ler *todos* os pesos da memória. Uma
vez por token. Então a velocidade é limitada por **banda de memória**, não por núcleos —
é por isso que 20 threads não salvam.

| Onde | Banda real | qwen3:8b Q4 (5,2GB) |
|---|---|---|
| VRAM (GPU) | ~336 GB/s | **35-45 tok/s** |
| RAM hoje (2 canais) | ~25 GB/s | **3-4 tok/s** |
| RAM com 4 canais | ~50 GB/s | 6-8 tok/s |

RAM não é VRAM lenta — é VRAM **10× mais lenta**. E offload parcial não ajuda tanto quanto
parece: você paga o preço do CPU pelas camadas que estão lá, a cada token. Com 25% das
camadas na RAM você já perde metade da velocidade.

**Onde CPU e RAM ganham de verdade** (e a spec já os usa assim):

- Whisper e Kokoro — compute-bound, modelos pequenos, 20 threads dão conta
- Embeddings de notas, quando chegar a hora
- Page cache: a troca entre `qwen3:4b` e `8b` fica instantânea em vez de ler do disco
- SQLite, backend, Docker

**A porta que se abre com upgrade de RAM.** Você tem 2 de 4 canais preenchidos numa X99
(Machinist E5-RS9, 4 slots, máx 128GB). Encher os 4 canais **dobra a banda de memória** —
esse é o ganho principal; capacidade é bônus.

Com ~64GB em quad-channel entra em jogo o **Qwen3-30B-A3B**: um MoE de 30B que só lê ~3B
de parâmetros ativos por token. A conta de banda passa a ser sobre 3B, não 30B. Estimativa
realista: **10-15 tok/s com qualidade de um modelo 30B** — outro patamar de assistente. E
dá pra ir além com offload híbrido (atenção na GPU, experts na RAM), técnica que o
llama.cpp suporta e que foi feita exatamente pra esse caso.

Custo: DDR4 ECC RDIMM usado de servidor é barato — a ordem de grandeza é R$300-500 por
64GB. **Confirme no manual da E5-RS9 se ela aceita RDIMM ECC antes de comprar**, e note
que não dá pra misturar com os UDIMM não-ECC atuais: é trocar tudo, não adicionar.

**Gatilho explícito:** se a suite de tool calling (§5.1) mostrar que o `qwen3:4b` não é
confiável em PT-BR, o upgrade de RAM vira a alternativa mais barata — e provavelmente mais
eficaz — que qualquer mudança de arquitetura. Não compre antes de medir.

---

## 10. Riscos

| # | Risco | Impacto | Mitigação |
|---|---|---|---|
| R1 | Qwen local erra tool calling em PT-BR | Mata o produto | Suite de 40 frases na semana 1, antes de construir |
| R2 | Latência de voz acima de 2s | Modo ligação vira inutilizável | Streaming em todas as etapas; medir por etapa desde o início |
| R3 | Régua de interrupção liga demais | Você desliga a proatividade | Orçamento diário + feedback + critério conjuntivo |
| R4 | Python 3.14 sem wheels do stack de ML | Trava o setup no dia 1 | Fixar 3.12 via `uv`; não usar o Python global |
| R5 | OAuth Google em modo Testing expira refresh token em 7 dias | Re-autenticar toda semana | Verificar na primeira hora de integração, não no mês 2 |
| R6 | Whisper erra nomes próprios | Atrito diário | Vocabulário pessoal (§5.3), na v1.5 e não depois |
| R7 | Prompt injection via email | Comprometimento real | Taint + separação de poder + confirmação (§5.9) |
| R8 | Duas camadas de UI divergem (Tauri vs RN) | Retrabalho e bugs só num lado | `/shared` concentra tipos, chamadas e lógica; UI fica fina dos dois lados |
| R9 | Android mata o WebSocket em background | Modo ligação no celular não toca | Foreground service com notificação persistente — resolver na v2.5, não antes |

---

## 11. Sobre o OpenJarvis

O clone em `../OpenJarvis` (Stanford / Hazy Research, Apache 2.0) **não é a base deste
projeto** — decisão tomada. Mas é referência de primeira linha pra três coisas:

- `src/openjarvis/speech/` — pipeline STT/TTS já resolvido
- `src/openjarvis/connectors/gcalendar.py`, `gmail.py` — integrações Google prontas
- `src/openjarvis/security/taint.py`, `injection_scanner.py` — exatamente o §5.9

Licença Apache 2.0 permite reaproveitar código com atribuição. Consultar antes de escrever
do zero é economia, não preguiça.

---

## 12. Multi-dispositivo — PC como servidor

Celular e notebook acessam o mesmo backend rodando no PC da §2. Não há réplica de dados
em lugar nenhum.

### Por que sincronização não é um problema aqui

Porque **não existe sincronização**. Existe um SQLite, num processo, numa máquina.
Celular e notebook são janelas pro mesmo servidor — clientes finos, sem estado próprio.
Sem réplica não há merge, sem merge não há conflito, sem conflito não há CRDT, vector
clock, nem resolução de divergência.

Isso é a maior economia de complexidade do projeto inteiro, e foi por isso que o cliente
único em React (§4) substituiu o Flutter: um codebase, três telas, zero estado duplicado.

### Rede: Tailscale

| | |
|---|---|
| Instala em | PC, celular, notebook (3 apps, ~15 min) |
| Cada um recebe | IP fixo `100.x.x.x`, estável em qualquer rede |
| Não precisa de | Port forward, DDNS, IP fixo do provedor, config de roteador |
| Funciona em | Wi-Fi de casa, 4G, rede de terceiro |
| Custo | Grátis no plano pessoal |

Hoje o PC só é alcançável dentro da rede de casa. Tailscale é o que
torna isso acessível de fora sem expor nada à internet.

### O que o app nativo resolveu de graça

Num navegador, `getUserMedia()` exige *secure context*. `http://100.x.x.x:8000` **não é**,
e o microfone simplesmente não é liberado — o que obrigaria a montar TLS antes de qualquer
teste de voz.

Com Tauri e React Native isso não existe: o app pede permissão de microfone ao sistema
operacional, como qualquer aplicativo. E como o Tailscale já cifra tudo (WireGuard),
**HTTP puro sobre a tailnet é aceitável** — TLS vira opcional, não pré-requisito.
Uma decisão de UI eliminou um módulo de infra inteiro.

### As duas armadilhas que sobraram

**1. Disponibilidade não é sincronização.**
O problema de verdade do multi-dispositivo aqui é o mesmo do §5.4: PC desligado, celular
sem nada. Mitigação:

- **Leitura offline (v1):** cache local no app (SQLite no RN, store do Tauri) das últimas
  notas, tarefas e agenda. Com o PC fora do ar, o celular ainda mostra o que importa,
  marcado como "dado de HH:MM".
- **Escrita offline:** fila local com last-write-wins na reconexão. Como é um usuário só,
  conflito real é raro — você não edita a mesma nota em dois aparelhos ao mesmo tempo.
  Mas isso reintroduz justamente a complexidade que o cliente fino eliminou, então
  **fica fora da v1**. Gatilho: só se anotar offline virar hábito de verdade.

**2. Voz no celular é mais difícil que voz no desktop.**
Soma o RTT da rede ao orçamento de 1,2s da §5.2 (~40-80ms em 4G decente — aceitável). Os
riscos reais são outros: manter o WebSocket vivo com o app em background (o Android mata
processo agressivamente — exige foreground service com notificação persistente), captura
de áudio contínua, e o Tailscale do Android em segundo plano. Por isso modo ligação no
celular é **v2.5**, depois de estar sólido no desktop.

### Matriz de dispositivos

| Dispositivo | SO | Papel | App | Chat | Modo ligação |
|---|---|---|---|---|---|
| PC (GTX 1660S) | Windows | **Servidor** + cliente | Tauri `.exe` | v1 | v1.5 |
| Notebook | Windows | Cliente | Tauri `.exe` | v1 | após o PC |
| Celular | Android | Cliente | RN `.apk` | v2.5 | v2.5 |

---

## 13. Pendências

- [ ] Nome do projeto
- [ ] Confirmar no manual da E5-RS9: aceita RDIMM ECC? Quantos canais com 4 pentes?
- [ ] Qualidade das vozes pt-BR do Kokoro — ouvir antes de fechar a decisão
- [ ] Definir remetentes prioritários e a janela de silêncio da régua de interrupção
- [ ] Conta Firebase pro FCM (push no Android) — gratuita, mas precisa existir
- [ ] Instalar Rust/cargo (pré-requisito do Tauri) — hoje ausente na máquina

---

## 14. ADRs a escrever

1. `0001-llm-local-e-roteamento-por-modo.md`
2. `0002-stt-e-tts-no-cpu.md`
3. `0003-apps-nativos-tauri-e-react-native.md`
4. `0004-regua-de-interrupcao.md`
5. `0005-modelo-de-seguranca-conteudo-externo.md`
