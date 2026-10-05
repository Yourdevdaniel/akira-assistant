"""Runner do Akira no Telegram.

Existe porque `jarvis gateway start` não funciona no Windows: sem `--install` ele
apenas imprime duas mensagens e sai, e com `--install` gera systemd/launchd, que
não existem aqui. Este script faz o que o gateway faria — conecta o canal, escuta
e responde — usando a API pública do OpenJarvis, sem tocar no repo dele.

Uso (da raiz do repositório, com o OpenJarvis em ./openjarvis):
    uv run --project openjarvis python runner/akira_telegram.py

Token e chats permitidos vêm de TELEGRAM_BOT_TOKEN e TELEGRAM_ALLOWED_CHAT_IDS
(ver .env.example) ou, se elas não existirem, de [channel.telegram] no
~/.openjarvis/config.toml.

Para parar: Ctrl+C.
"""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import tomllib
from pathlib import Path

import conversa
import tarefas

CONFIG = Path.home() / ".openjarvis" / "config.toml"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("akira")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)


def ler_config() -> dict:
    if not CONFIG.exists():
        sys.exit(f"Config não encontrado: {CONFIG}")
    with CONFIG.open("rb") as fh:
        cfg = tomllib.load(fh)

    tg = cfg.get("channel", {}).get("telegram", {})
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or tg.get("bot_token", "")).strip()
    if not token or token.startswith("PREENCHER"):
        sys.exit("Token do bot ausente: defina TELEGRAM_BOT_TOKEN ou [channel.telegram]")

    ids = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS") or tg.get("allowed_chat_ids", "")
    permitidos = {c.strip() for c in ids.split(",") if c.strip()}
    if not permitidos:
        log.warning(
            "Nenhum chat permitido: QUALQUER pessoa que achar o bot fala com esta "
            "máquina. Defina TELEGRAM_ALLOWED_CHAT_IDS."
        )

    return {
        "token": token,
        "permitidos": permitidos,
        "agente": cfg.get("agent", {}).get("default_agent", "simple"),
        "modelo": cfg.get("intelligence", {}).get("default_model", ""),
    }


def carregar_whisper():
    """Whisper configurado em [speech], ou None se não carregar.

    Carrega na subida (uns 3 s) para o primeiro áudio não esperar, e fica na
    memória: o modelo small ocupa uns 370 MB da placa.
    """
    from openjarvis.core.config import load_config
    from openjarvis.speech._discovery import get_speech_backend

    config = load_config()
    stt = get_speech_backend(config)
    if stt is None:
        log.warning("Whisper não carregou: áudios vão receber um aviso, não resposta.")
    else:
        log.info("Whisper pronto (modelo %s)", config.speech.model)
    return stt, config.speech.language or None


def main() -> int:
    cfg = ler_config()

    from openjarvis.channels.telegram import TelegramChannel
    from openjarvis.core.events import EventBus
    from openjarvis.core.types import Message, Role
    from openjarvis.sdk import Jarvis

    log.info("Carregando o Akira (modelo: %s, agente: %s)…", cfg["modelo"], cfg["agente"])
    jarvis = Jarvis()
    # Os agentes levam uns 4 s para importar; melhor na subida que na 1ª mensagem.
    import openjarvis.agents  # noqa: F401

    stt, idioma = carregar_whisper()
    lista = tarefas.Lista()
    log.info("Lista de tarefas em %s", tarefas.BANCO)
    historico = conversa.Historico()

    canal = TelegramChannel(
        bot_token=cfg["token"],
        bus=EventBus(),
        allowed_chat_ids=",".join(cfg["permitidos"]),
    )

    # O poller do Telegram não pode ficar bloqueado enquanto o modelo pensa:
    # mensagens que chegassem nesse meio-tempo seriam perdidas. Por isso o
    # handler só enfileira, e um worker separado responde uma de cada vez.
    fila: queue.Queue = queue.Queue()

    def ao_receber(msg) -> None:
        # conversation_id é o chat_id. `channel` vale a string "telegram" —
        # olhar para ele aqui rejeita todo mundo.
        chat = str(getattr(msg, "conversation_id", "") or "")
        texto = (getattr(msg, "content", "") or "").strip()
        # Mensagem de voz: o canal manda os bytes e a transcrição fica no
        # worker, porque leva segundos e travaria o poller.
        meta = getattr(msg, "metadata", None) or {}
        audio = meta.get("audio")
        # O canal já aplica a allow-list antes de chamar este handler; isto é
        # só uma segunda tranca, caso o token vaze e o config do canal mude.
        if cfg["permitidos"] and chat not in cfg["permitidos"]:
            log.warning("Ignorado: chat %s fora da allow-list", chat)
            return
        if not texto and not audio:
            return
        log.info("← %s", f"áudio de {len(audio) // 1024} KB" if audio else texto[:70])
        fila.put((chat, texto, audio, meta.get("audio_format", "ogg")))

    def ouvir(audio: bytes, formato: str) -> tuple[str, str]:
        """Transcreve o áudio. Devolve (texto, aviso); só um dos dois vem."""
        if stt is None:
            return "", "O Whisper não carregou, então não consigo ouvir áudio agora."
        try:
            texto = stt.transcribe(audio, format=formato, language=idioma).text.strip()
        except Exception:
            log.exception("Falha ao transcrever")
            return "", "Não consegui transcrever o áudio. Pode mandar por texto?"
        if not texto:
            return "", "Não entendi nada nesse áudio. Pode repetir?"
        return texto, ""

    def responder(chat: str, texto: str) -> str:
        """Tarefa primeiro (anotar, listar, riscar); o resto vai para o modelo.

        Só a conversa entra no histórico. As respostas da lista ficam de fora
        para o modelo não aprender a imitar "Anotado:" sem ter anotado.
        """
        try:
            resposta = tarefas.responder(
                texto, lista, lambda frase: tarefas.entender(frase, cfg["modelo"])
            )
            if resposta is not None:
                return resposta
        except Exception:
            log.exception("Falha na lista de tarefas; respondendo como conversa")
        anteriores = [
            Message(role=Role(papel), content=fala) for papel, fala in historico.mensagens(chat)
        ]
        try:
            resposta = jarvis.ask(
                texto,
                agent=cfg["agente"] or None,
                history=[Message(role=Role.SYSTEM, content=conversa.REGRA_DA_LISTA), *anteriores],
            )
        except Exception as exc:
            log.exception("Falha ao responder")
            return f"Erro ao processar: {type(exc).__name__}: {exc}"
        resposta = conversa.sem_falsa_anotacao((resposta or "").strip() or "(resposta vazia)")
        historico.guardar(chat, texto, resposta)
        return resposta

    def worker() -> None:
        while True:
            chat, texto, audio, formato = fila.get()
            ouvido, resposta = "", ""
            if audio:
                ouvido, resposta = ouvir(audio, formato)
                if ouvido:
                    log.info("ouvi: %s", ouvido[:70])
                    # Legenda do áudio, se houver, vem antes da fala.
                    texto = f"{texto}\n{ouvido}".strip()
            if not resposta:
                resposta = responder(chat, texto)
            if ouvido:
                # Mostra o que foi entendido: erro de transcrição fica visível.
                resposta = f"🎙️ {ouvido}\n\n{resposta}"
            try:
                canal.send(chat, resposta)
                log.info("→ %s", resposta[:70].replace("\n", " "))
            except Exception:
                log.exception("Falha ao enviar pelo Telegram")
            finally:
                fila.task_done()

    threading.Thread(target=worker, daemon=True, name="akira-worker").start()

    canal.on_message(ao_receber)
    canal.connect()
    log.info("Akira no ar. Manda mensagem no Telegram. Ctrl+C para parar.")

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        log.info("Encerrando…")
    finally:
        try:
            canal.disconnect()
        except Exception:
            pass
        jarvis.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
