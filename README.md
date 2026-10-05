# Akira Assistant

A personal assistant that runs on my own Windows PC and talks to me on Telegram, in Brazilian Portuguese, by text or voice.

## What it does

- **To-do list by text or voice note.** Add, list, complete, delete and undo tasks the way you would say it to a person. Due dates like "até sexta", "dia 3" or "semana que vem" are understood.
- **Morning digest at 08:00.** Reads Gmail and Google Calendar, writes a short summary and sends it to Telegram as text and as Portuguese audio. Tasks due today and overdue tasks are appended at the end.
- **Short conversation memory.** Follow-up questions work ("qual a capital do Canadá?" then "e quantos habitantes tem lá?"): it keeps the last 10 messages of the last 2 hours per chat.
- **Bank statement import.** A command-line tool imports OFX or CSV statements into a local SQLite database, with rule-based categories and duplicate protection.
- **Evaluation sets** to decide which local model is good enough before switching.

| You send (pt-BR) | It does |
|---|---|
| "me lembra de pagar o boleto até sexta" | `Anotado: pagar o boleto (sex 25/09).` |
| "anota: renovar a CNH, é urgente" | adds it with high priority |
| "o que eu tenho pra fazer?" or `tarefas` | numbered list, closest due date first |
| "já paguei o boleto" or `feito 2` | marks it done |
| "tira da lista a academia" or `apaga 3` | removes it without marking it done |
| `desfaz` | undoes the last change |

Every reply about the list is built by code, never by the model. If a reply does not start with "Anotado", "Feito", "Tirei" or "Desfeito", the list did not change.

## How it works

```
Telegram (phone or laptop)
        |
        v
runner/akira_telegram.py        polls Telegram, queues messages, one worker thread
  |-- voice note --> Whisper "small" (faster-whisper, local) --> text
  |-- runner/tarefas.py         llama3.2:3b via Ollama answers a constrained JSON:
  |                             {acao, titulo, prazo, prioridade, busca}
  |                             code resolves the date, finds the task,
  |                             writes SQLite and writes the reply
  |-- anything else -->         OpenJarvis agent + llama3.2:3b, with the last 10 messages
        |
        v
reply on Telegram

Windows Task Scheduler, 08:00 --> resumo-diario.cmd --> runner/resumo_telegram.py
  OpenJarvis morning digest: Gmail + Calendar (Google APIs) --> llama3.2:3b writes
  --> tasks due today added by code --> Kokoro-82M reads it aloud --> Telegram
```

The main design decision: **the model classifies, the code decides.** Small local models pick the right intent most of the time but get dates wrong while sounding sure (see Measurements). So the model only returns one of five actions plus the words the user said, through Ollama's JSON schema mode (`format`). Dates are parsed by plain Python (`resolver_prazo`), the task is found by word overlap, and the reply is a template. A few guards sit around the model:

- Short commands (`tarefas`, `feito 2`, `desfaz`) never reach the model.
- "concluir" (mark as done) is downgraded to "criar" unless the sentence has a past-tense or "já/feito" signal, so "preciso pagar o IPVA" can never tick off "pagar o IPVA".
- If the chat model replies "Anotado..." on its own, the runner replaces it with a message saying the list did not change.

Other pieces:

- **OpenJarvis** ([open-jarvis/OpenJarvis](https://github.com/open-jarvis/OpenJarvis), Apache-2.0) provides the agent runtime, the Telegram channel, the Google connectors, Whisper and Kokoro wrappers and the morning digest agent. Akira needs a few changes to it, shipped as `patches/openjarvis-local.patch`: conversation history in `Jarvis.ask()`, voice notes delivered to handlers, and a Portuguese digest (prompt, spoken currency, cleaner email previews).
- **Storage:** tasks live in SQLite at `~/.openjarvis/tarefas.db`. Nothing is hard-deleted; done and removed are statuses. Conversation memory is kept in process memory only and resets on restart.
- **No cloud model at runtime.** Everything above runs on the PC. The original plan was to hand calendar writes and email drafting to Claude, because local models get dates wrong; that bridge is not built.

The design draft written before the code is in `docs/SPEC.md` (Portuguese). The implementation diverged from it in several places.

## Measurements

Hardware: NVIDIA GTX 1660 SUPER (6 GB VRAM), Intel Xeon E5-2650 v3 (10 cores, 20 threads), 16 GB DDR4 (from `docs/SPEC.md`). The evaluation sets fix "today" as Monday 2026-09-21 so that relative dates can be checked. Raw logs are in `medicoes/`, raw outputs in `evals/`.

**Task classifier (constrained JSON)**, `evals/tarefas.py`: 41 phrases, 10 of them written after the prompt was tuned. Source: `medicoes/eval-tarefas.txt`.

| Model | All fields right | New phrases only | Median | p95 |
|---|---|---|---|---|
| llama3.2:3b | 41/41 | 10/10 | 0.7 s | 0.9 s |
| qwen2.5:7b | 41/41 | 10/10 | 3.1 s | 4.0 s |

**Free-form tool calling**, `evals/rodar.py`: 40 pt-BR phrases across 10 tools (calendar, tasks, notes, email). Source: `medicoes/eval-toolcalling-llama-qwen25.txt`.

| Model | Right tool | Right tool and arguments | Median |
|---|---|---|---|
| llama3.2:3b | 31/40 (78%) | 26/40 (65%) | 2.7 s |
| qwen2.5:7b | 39/40 (98%) | 33/40 (82%) | 5.5 s |

On the 12 calendar phrases, llama3.2:3b got 6 right and qwen2.5:7b got 7. Of the 11 misses, 8 were wrong dates (for example "semana que vem terça" resolved to Monday the 28th instead of Tuesday the 29th). That is why dates moved out of the model.

Models that were dropped:

- **hermes3:3b**, first 10 phrases of the same set: right tool 2/10, right tool and arguments 0/10 (llama3.2:3b on the same 10: 8/10 and 5/10). Source: `medicoes/eval-hermes.txt`.
- **qwen3:4b**: 35 to 88 s per phrase; the run was stopped after 23 of 40 phrases. Source: `medicoes/eval-toolcalling.txt`.

**Kokoro-82M text to speech**, one 62-character sentence (4.0 s of audio). Source: `medicoes/bench-tts.txt`.

| Device | Synthesis time | Real-time factor | VRAM |
|---|---|---|---|
| CUDA (GTX 1660 SUPER) | 0.32 s | 0.08 | 577 MB |
| CPU (Xeon E5-2650 v3) | 2.18 s | 0.54 | |

Real-time factor is synthesis time divided by audio length; lower is faster.

Person and bank names in the evaluation phrases and saved outputs were replaced with placeholders before publishing. The runs used the original names.

## Run it

Windows-first: the launchers are `.cmd` files and the digest uses Windows Task Scheduler.

**Prerequisites**

- Python 3.12 (OpenJarvis requires Python below 3.14; the runner needs 3.11 or newer).
- [uv](https://docs.astral.sh/uv/) and git.
- [Ollama](https://ollama.com/) running locally, then `ollama pull llama3.2:3b`.
- Optional: an NVIDIA GPU with CUDA. Whisper and Kokoro also run on the CPU, slower (see the table above). For the GPU, the OpenJarvis environment needs a CUDA build of PyTorch (this machine used torch 2.6.0 with CUDA 12.4, see [pytorch.org](https://pytorch.org/get-started/locally/)).
- A Telegram account and a Google account.

**1. Get the code and OpenJarvis**

```
git clone https://github.com/Yourdevdaniel/akira-assistant
cd akira-assistant
git clone https://github.com/open-jarvis/OpenJarvis openjarvis
cd openjarvis
git checkout 93c1f87ab65e22cdd442a27da1e22aaf6f6b301e
git apply ../patches/openjarvis-local.patch
uv sync --python 3.12 --extra speech --extra voice
cd ..
```

`openjarvis/` is ignored by git. To keep it somewhere else, set `OPENJARVIS_DIR` in `.env`.

**2. Telegram bot**

In Telegram, talk to @BotFather, send `/newbot` and copy the token. Send any message to your new bot, open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `message.chat.id`. Then:

```
copy .env.example .env
```

and fill in `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_CHAT_IDS`. Every variable is explained in `.env.example`.

**3. OpenJarvis config**

```
mkdir %USERPROFILE%\.openjarvis
copy config.example.toml %USERPROFILE%\.openjarvis\config.toml
```

It sets the model, Whisper, the Portuguese digest with a Kokoro pt-BR voice, and turns off OpenJarvis usage analytics.

**4. Google OAuth (Gmail and Calendar)**

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and enable the Gmail API and the Google Calendar API.
2. Configure the OAuth consent screen as External, keep it in Testing and add your Google account as a test user.
3. Create an OAuth client of type **Desktop app** and download the JSON.
4. Save it as `%USERPROFILE%\.openjarvis\connectors\google.json`.
5. Run the first login, which opens the browser:

```
uv run --project openjarvis python runner/conectar_google.py
```

In Testing mode Google expires the refresh token after 7 days; run the script again when that happens.

**5. Start**

Double-click `iniciar-akira.cmd` (or run it from a terminal). After about 20 seconds it prints "Akira no ar"; send a message on Telegram. Closing the window stops it. Logs go to `logs/`.

**6. Morning digest**

Send one now with `resumo-diario.cmd`. To schedule it every day at 08:00, in PowerShell from the repo folder:

```powershell
$action   = New-ScheduledTaskAction -Execute "$PWD\resumo-diario.cmd"
$trigger  = New-ScheduledTaskTrigger -Daily -At 08:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName "Akira - resumo diario" -Action $action -Trigger $trigger -Settings $settings
```

`-StartWhenAvailable` runs it when the PC is turned on if it was off at 08:00.

Other options: `uv run --project openjarvis python runner/resumo_telegram.py --cache` resends the last digest, `--sem-audio` sends text only.

**Optional: bank statements and model comparisons**

```
python financas/importar.py statement.ofx --conta corrente
python financas/importar.py --resumo
python evals/tarefas.py --modelos llama3.2:3b
python evals/rodar.py --modelos llama3.2:3b --falhas
```

The finance database is created at `financas/financas.db` (ignored by git). The evals need Ollama running and overwrite their JSON output in `evals/`.

## Tests

The tests cover the task list and the conversation memory (`runner/tarefas.py`, `runner/conversa.py`). They use only the standard library and pytest, and need no Ollama, GPU, Google or Telegram:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest tests
```

The OpenJarvis patch has its own tests, run inside the OpenJarvis checkout:

```
cd openjarvis
uv run --extra dev python -m pytest tests/agents/test_morning_digest.py tests/channels/test_telegram.py tests/sdk/test_sdk.py tests/tools/test_digest_collect.py
```

## Privacy

- **Local:** the language model (Ollama), Whisper, Kokoro, the task list and the finance database run and stay on the PC. No cloud language model is called.
- **Telegram:** your messages, voice notes, the replies and the daily digest (text and audio) go through Telegram's servers, as with any bot. Only chat IDs in `TELEGRAM_ALLOWED_CHAT_IDS` get answers; the allow-list is checked by the channel and again by the runner.
- **Google:** Gmail and Calendar are read through Google's APIs with your own OAuth token. The summary is written locally and then sent to your Telegram chat. Akira's code never sends email or edits the calendar.
- **Secrets and data stay out of the repo:** `.env`, `~/.openjarvis/config.toml`, `~/.openjarvis/connectors/google.json` (OAuth token), `~/.openjarvis/tarefas.db`, `logs/` and `financas/*.db` are outside the repo or ignored by `.gitignore`. Logs contain message text and chat IDs; keep them private.
- **OpenJarvis analytics:** upstream OpenJarvis sends anonymous usage events by default. `config.example.toml` sets `[analytics] enabled = false`; `jarvis init --force` rewrites the config and drops that line.
- Model weights are downloaded once from Ollama and Hugging Face.

## Status

Personal project, Windows-first, in daily use on one machine. Identifiers, comments and the design doc are in Portuguese because the assistant is. Not done yet: a reminder at the due time, long-term notes, follow-ups like "e pão também" right after "anota comprar leite", reading transactions from bank emails, and the Claude bridge for calendar writes.

## How it was built

I built it with Claude Code as an AI pair programmer. I set the scope and requirements (Portuguese text and voice, a morning digest at 8:00, everything running on my own machine), wired it to my Google and Telegram accounts on my hardware, and validate every change with the evaluation set and daily use. It is an application of pretrained models (a local LLM through Ollama, Whisper and Kokoro), not model training.

## License

MIT, see `LICENSE`. OpenJarvis is Apache-2.0 and is not included; `patches/openjarvis-local.patch` is a derivative of it under Apache-2.0. See `NOTICE`.

## Versão em português

Assistente pessoal que roda no meu PC com Windows e conversa comigo pelo Telegram, em português, por texto ou áudio. Cuida de uma lista de tarefas (anotar, listar, concluir, apagar, desfazer), manda às 8h um resumo do Gmail e do Google Calendar em texto e áudio, com as tarefas que vencem no dia, lembra das últimas mensagens da conversa e importa extratos bancários (OFX/CSV) para um SQLite local.

O modelo local (`llama3.2:3b` via Ollama) só classifica a mensagem num JSON travado; data, busca da tarefa e resposta são código, porque o modelo erra data com cara de certa. Medido: o classificador acertou 41 de 41 frases a 0,7 s por mensagem, contra 65% do mesmo modelo com tool calling livre. Whisper transcreve os áudios e o Kokoro lê o resumo, tudo na máquina. Roda sobre o OpenJarvis (Apache-2.0), com as mudanças em `patches/`.

Desenvolvi com o Claude Code como par de programação com IA: defini o escopo e os requisitos (texto e voz em português, resumo matinal às 8h, tudo rodando na minha máquina), integrei com minhas contas Google e Telegram no meu hardware e valido cada mudança com o conjunto de testes e o uso diário. É uma aplicação de modelos pré-treinados (LLM local via Ollama, Whisper e Kokoro), não treinamento de modelo.
