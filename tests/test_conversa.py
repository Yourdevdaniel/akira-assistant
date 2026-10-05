"""Testes da memória curta da conversa (runner/conversa.py)."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "runner"))

from conversa import Historico, sem_falsa_anotacao  # noqa: E402


class Relogio:
    def __init__(self):
        self.agora = datetime(2026, 9, 25, 9, 0)

    def __call__(self):
        return self.agora


def test_guarda_em_ordem_e_separa_por_chat():
    historico = Historico()
    historico.guardar("1", "capital do Canadá?", "Ottawa.")
    historico.guardar("2", "oi", "Oi!")
    historico.guardar("1", "e a população?", "Cerca de 1 milhão.")

    assert historico.mensagens("1") == [
        ("user", "capital do Canadá?"),
        ("assistant", "Ottawa."),
        ("user", "e a população?"),
        ("assistant", "Cerca de 1 milhão."),
    ]
    assert historico.mensagens("2") == [("user", "oi"), ("assistant", "Oi!")]
    assert historico.mensagens("3") == []


def test_guarda_so_as_ultimas():
    historico = Historico(maximo=4)
    for i in range(3):
        historico.guardar("1", f"pergunta {i}", f"resposta {i}")

    assert historico.mensagens("1") == [
        ("user", "pergunta 1"),
        ("assistant", "resposta 1"),
        ("user", "pergunta 2"),
        ("assistant", "resposta 2"),
    ]


def test_esquece_o_que_passou_da_validade():
    relogio = Relogio()
    historico = Historico(validade=timedelta(hours=2), agora=relogio)
    historico.guardar("1", "de manhã", "ok")
    relogio.agora += timedelta(hours=1)
    historico.guardar("1", "uma hora depois", "ok")

    relogio.agora += timedelta(hours=1, minutes=30)
    assert historico.mensagens("1") == [("user", "uma hora depois"), ("assistant", "ok")]

    relogio.agora += timedelta(hours=1)
    assert historico.mensagens("1") == []


@pytest.mark.parametrize(
    "resposta",
    ["Anotado: comprar pão.", "**Anotado**: pão", "Feito: pagar boleto.", "Tirei da lista o pão."],
)
def test_resposta_que_finge_mexer_na_lista_vira_honesta(resposta):
    assert sem_falsa_anotacao(resposta).startswith("Não mexi na sua lista")


@pytest.mark.parametrize(
    "resposta",
    ["Ottawa.", "Feito isso, o bolo vai ao forno.", "Você pediu para anotar o leite antes."],
)
def test_resposta_normal_passa(resposta):
    assert sem_falsa_anotacao(resposta) == resposta
