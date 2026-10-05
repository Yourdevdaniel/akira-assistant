"""Gera o resumo do dia e entrega no Telegram, em texto e em áudio.

No fim do resumo entram as tarefas que vencem hoje e as atrasadas, da lista
que o Akira guarda (runner/tarefas.py).

Uso (da raiz do repositório, com o OpenJarvis em ./openjarvis):
    uv run --project openjarvis python runner/resumo_telegram.py
    uv run --project openjarvis python runner/resumo_telegram.py --cache    # não regera, manda o último

Manda para o primeiro chat de TELEGRAM_ALLOWED_CHAT_IDS (ou de
[channel.telegram] no config.toml). Pensado para rodar sozinho pelo Agendador
de Tarefas do Windows.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tomllib
import urllib.request
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import tarefas

CONFIG = Path.home() / ".openjarvis" / "config.toml"
API = "https://api.telegram.org/bot{token}/{metodo}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("resumo")


def ler_config() -> tuple[str, str]:
    if not CONFIG.exists():
        sys.exit(f"Config não encontrado: {CONFIG}")
    with CONFIG.open("rb") as fh:
        cfg = tomllib.load(fh)
    tg = cfg.get("channel", {}).get("telegram", {})
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or tg.get("bot_token", "")).strip()
    ids = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS") or tg.get("allowed_chat_ids", "")
    chats = [c.strip() for c in ids.split(",") if c.strip()]
    if not token:
        sys.exit("Token do bot ausente: defina TELEGRAM_BOT_TOKEN ou [channel.telegram]")
    if not chats:
        sys.exit("Nenhum chat permitido: não sei para quem mandar o resumo")
    return token, chats[0]


def _post(token: str, metodo: str, campos: dict, arquivo: tuple | None = None) -> dict:
    """POST no Bot API. Usa multipart só quando há arquivo — evita dependência."""
    url = API.format(token=token, metodo=metodo)

    if arquivo is None:
        dados = json.dumps(campos).encode()
        req = urllib.request.Request(
            url, data=dados, headers={"Content-Type": "application/json"}
        )
    else:
        nome_campo, nome_arquivo, conteudo = arquivo
        limite = "----akira" + "".join(f"{b:02x}" for b in Path(__file__).name.encode()[:8])
        corpo = bytearray()
        for k, v in campos.items():
            corpo += f"--{limite}\r\n".encode()
            corpo += f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode()
            corpo += f"{v}\r\n".encode()
        corpo += f"--{limite}\r\n".encode()
        corpo += (
            f'Content-Disposition: form-data; name="{nome_campo}"; '
            f'filename="{nome_arquivo}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        corpo += conteudo + b"\r\n"
        corpo += f"--{limite}--\r\n".encode()
        req = urllib.request.Request(
            url,
            data=bytes(corpo),
            headers={"Content-Type": f"multipart/form-data; boundary={limite}"},
        )

    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def enviar_texto(token: str, chat: str, texto: str) -> None:
    # 4096 é o limite do Telegram; corta em quebra de linha para não picar frase.
    LIMITE = 4000
    while texto:
        if len(texto) <= LIMITE:
            pedaco, texto = texto, ""
        else:
            corte = texto.rfind("\n", 0, LIMITE)
            corte = corte if corte > LIMITE // 2 else LIMITE
            pedaco, texto = texto[:corte], texto[corte:].lstrip()
        r = _post(token, "sendMessage", {"chat_id": chat, "text": pedaco})
        if not r.get("ok"):
            log.error("Telegram recusou o texto: %s", r)


def enviar_audio(token: str, chat: str, caminho: Path) -> None:
    if not caminho.exists():
        log.warning("Áudio não encontrado: %s", caminho)
        return
    mb = caminho.stat().st_size / 1_000_000
    if mb > 45:
        log.warning("Áudio de %.1fMB acima do limite do Telegram; pulando", mb)
        return
    r = _post(
        token,
        "sendAudio",
        {"chat_id": chat, "title": "Resumo do dia"},
        ("audio", caminho.name, caminho.read_bytes()),
    )
    if not r.get("ok"):
        log.error("Telegram recusou o áudio: %s", r)
    else:
        log.info("áudio enviado (%.1fMB)", mb)


def com_tarefas(artefato, paragrafo: str):
    """O resumo com o parágrafo das tarefas no fim, no texto e no áudio.

    O áudio é refeito inteiro, não emendado: sai numa voz só e sem corte.
    Custa uns segundos de GPU a mais, uma vez por dia.
    """
    # _spoken_money é do nosso fork do OpenJarvis: "R$ 50" num título vira
    # "50 reais" no áudio; o texto guarda o título como a pessoa escreveu.
    from openjarvis.agents.morning_digest import _spoken_money
    from openjarvis.core.config import load_config
    from openjarvis.core.paths import get_config_dir
    from openjarvis.tools.text_to_speech import TextToSpeechTool

    texto = f"{artefato.text.strip()}\n\n{paragrafo}"
    dc = load_config().digest
    voz = TextToSpeechTool().execute(
        text=_spoken_money(texto),
        voice_id=dc.voice_id,
        backend=dc.tts_backend,
        speed=dc.voice_speed,
        output_dir=str(get_config_dir() / "digests"),
    )
    audio = artefato.audio_path
    if voz.success:
        audio = Path(voz.metadata["audio_path"])
    else:
        log.warning("Voz falhou (%s); o áudio vai sem as tarefas", voz.content)
    return replace(artefato, text=texto, audio_path=audio, generated_at=datetime.now())


def main() -> int:
    p = argparse.ArgumentParser(description="Manda o resumo do dia no Telegram.")
    p.add_argument("--cache", action="store_true", help="não regera; manda o último")
    p.add_argument("--sem-audio", action="store_true", help="só texto")
    a = p.parse_args()

    token, chat = ler_config()

    from openjarvis.agents.digest_store import DigestStore

    if not a.cache:
        log.info("Gerando o resumo (lê agenda e e-mail; costuma levar alguns minutos)…")
        from openjarvis.sdk import Jarvis

        try:
            with Jarvis() as j:
                j.ask("Generate my morning digest", agent="morning_digest")
        except Exception as exc:
            log.exception("Falha ao gerar o resumo")
            enviar_texto(token, chat, f"Não consegui montar o resumo de hoje.\n{exc}")
            return 1

    store = DigestStore()
    try:
        artefato = store.get_latest()
        if artefato is not None and not a.cache:
            try:
                paragrafo = tarefas.paragrafo_do_dia(tarefas.Lista().pendentes(), date.today())
            except Exception:
                log.exception("Não consegui ler a lista de tarefas; o resumo vai sem elas")
                paragrafo = ""
            if paragrafo:
                log.info("tarefas no resumo: %s", paragrafo)
                artefato = com_tarefas(artefato, paragrafo)
                store.save(artefato)  # o --cache reenvia já com as tarefas
    finally:
        store.close()

    if artefato is None:
        enviar_texto(token, chat, "Nenhum resumo disponível.")
        return 1

    log.info("enviando para o chat %s", chat)
    enviar_texto(token, chat, artefato.text.strip())

    if not a.sem_audio and artefato.audio_path:
        enviar_audio(token, chat, Path(str(artefato.audio_path)))

    log.info("resumo entregue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
