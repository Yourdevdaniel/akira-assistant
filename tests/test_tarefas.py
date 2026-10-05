"""Testes da lista de tarefas (runner/tarefas.py). Rodar da raiz do repositório:

    python -m pytest tests
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "runner"))

from tarefas import (  # noqa: E402
    Lista,
    Tarefa,
    achar,
    paragrafo_do_dia,
    quando,
    resolver_prazo,
    responder,
)

# Mesma "hoje" dos evals: segunda, 21/09/2026.
HOJE = date(2026, 9, 21)


@pytest.mark.parametrize(
    ("frase", "esperado"),
    [
        ("até sexta", date(2026, 9, 25)),
        ("pra quarta-feira", date(2026, 9, 23)),
        ("amanhã de manhã", date(2026, 9, 22)),
        ("depois de amanhã", date(2026, 9, 23)),
        ("hoje à noite", HOJE),
        ("até segunda", HOJE),  # dita numa segunda: hoje, não daqui a 7 dias
        ("segunda que vem", date(2026, 9, 28)),
        ("semana que vem", date(2026, 9, 28)),
        ("terça da semana que vem", date(2026, 9, 29)),
        ("fim de semana", date(2026, 9, 26)),
        ("até o fim do mês", date(2026, 9, 30)),
        ("daqui a 3 dias", date(2026, 9, 24)),
        ("daqui a uma semana", date(2026, 9, 28)),
        ("dia 30", date(2026, 9, 30)),
        ("dia 3", date(2026, 10, 3)),  # já passou este mês
        ("dia 31", date(2026, 10, 31)),  # setembro não tem 31
        ("dia 3 do mês que vem", date(2026, 10, 3)),
        ("dia primeiro", date(2026, 10, 1)),
        ("10/10", date(2026, 10, 10)),
        ("01/02", date(2027, 2, 1)),
        ("15/11/2027", date(2027, 11, 15)),
        ("quando der", None),
        ("31/02", None),
    ],
)
def test_resolver_prazo(frase, esperado):
    assert resolver_prazo(frase, HOJE) == esperado


def test_quando():
    assert quando(HOJE, HOJE) == "hoje"
    assert quando(date(2026, 9, 22), HOJE) == "amanhã"
    assert quando(date(2026, 9, 25), HOJE) == "sex 25/09"
    assert quando(date(2026, 9, 18), HOJE) == "sex 18/09, atrasada"
    assert quando(None, HOJE) == ""


def test_paragrafo_do_dia():
    pendentes = [
        Tarefa(1, "renovar a CNH", date(2026, 8, 30)),
        Tarefa(2, "comprar ração", date(2026, 9, 15)),  # terça passada
        Tarefa(3, "levar o carro", date(2026, 9, 15)),
        Tarefa(4, "ligar pro contador", date(2026, 9, 20)),  # ontem
        Tarefa(5, "pagar o boleto", HOJE),
        Tarefa(6, "marcar dentista", date(2026, 9, 22)),  # amanhã: fica de fora
        Tarefa(7, "trocar a lâmpada"),  # sem prazo: fica de fora
    ]

    assert paragrafo_do_dia(pendentes, HOJE) == (
        "Na sua lista, vence hoje: pagar o boleto. "
        "Está atrasada desde 30 de agosto: renovar a CNH. "
        "Estão atrasadas desde terça: comprar ração e levar o carro. "
        "Está atrasada desde ontem: ligar pro contador."
    )
    assert paragrafo_do_dia(pendentes[3:4], HOJE) == (
        "Na sua lista, está atrasada desde ontem: ligar pro contador."
    )
    assert paragrafo_do_dia(pendentes[5:], HOJE) == ""


def test_lista_ordena_por_prazo_e_esconde_concluidas(tmp_path):
    lista = Lista(tmp_path / "t.db")
    sem_prazo = lista.criar("comprar ração", None, "normal")
    sexta = lista.criar("pagar boleto", date(2026, 9, 25), "normal")
    sexta_alta = lista.criar("revisar contrato", date(2026, 9, 25), "alta")
    amanha = lista.criar("ligar pro contador", date(2026, 9, 22), "normal")

    assert lista.pendentes() == [amanha, sexta_alta, sexta, sem_prazo]

    lista.marcar(sexta, "feita")
    lista.marcar(sem_prazo, "apagada")
    assert lista.pendentes() == [amanha, sexta_alta]


def test_achar():
    pendentes = [
        Tarefa(1, "pagar o boleto da internet"),
        Tarefa(2, "pagar o boleto do cartão"),
        Tarefa(3, "comprar ração pro cachorro"),
    ]
    assert achar(pendentes, "ração do cachorro") == [pendentes[2]]
    assert achar(pendentes, "boletos da internet") == [pendentes[0]]
    assert achar(pendentes, "paguei o boleto") == pendentes[:2]  # empate
    assert achar(pendentes, "2") == [pendentes[1]]
    assert achar(pendentes, "9") == []
    assert achar(pendentes, "dentista") == []


class Modelo:
    """Classificador falso: devolve o pedido dado e conta as chamadas."""

    def __init__(self, pedido=None):
        self.pedido = pedido or {}
        self.chamadas = 0

    def __call__(self, texto):
        self.chamadas += 1
        return self.pedido


def criar(titulo, prazo="", prioridade="normal"):
    return Modelo(
        {"acao": "criar", "titulo": titulo, "prazo": prazo, "prioridade": prioridade}
    )


def test_criar_com_prazo_e_prioridade(tmp_path):
    lista = Lista(tmp_path / "t.db")
    resposta = responder(
        "anota revisar o contrato até sexta, é urgente",
        lista,
        criar("revisar o contrato", "até sexta", "alta"),
        HOJE,
    )
    assert resposta == "Anotado: revisar o contrato (sex 25/09, prioridade alta)."
    assert lista.pendentes()[0].prazo == date(2026, 9, 25)


def test_criar_com_prazo_que_nao_entende(tmp_path):
    lista = Lista(tmp_path / "t.db")
    resposta = responder("x", lista, criar("ligar pra mãe", "quando der"), HOJE)
    assert resposta == (
        'Anotado: ligar pra mãe. Não entendi o prazo "quando der", '
        "então ficou sem data."
    )


def test_listar_numera_na_ordem_da_lista(tmp_path):
    lista = Lista(tmp_path / "t.db")
    lista.criar("comprar ração", None, "normal")
    lista.criar("pagar boleto", date(2026, 9, 22), "normal")

    resposta = responder("o que falta?", lista, Modelo({"acao": "listar"}), HOJE)

    assert resposta == "Pendentes:\n1. pagar boleto (amanhã)\n2. comprar ração"
    vazia = Lista(tmp_path / "vazia.db")
    assert responder("x", vazia, Modelo({"acao": "listar"}), HOJE) == (
        "Nada pendente na sua lista."
    )


def test_concluir_pela_descricao(tmp_path):
    lista = Lista(tmp_path / "t.db")
    lista.criar("pagar o boleto da internet", None, "normal")
    lista.criar("comprar ração", None, "normal")

    modelo = Modelo({"acao": "concluir", "busca": "boleto internet"})
    resposta = responder("já paguei o boleto da internet", lista, modelo, HOJE)

    assert resposta == "Feito: pagar o boleto da internet. Faltam 1."
    assert [t.titulo for t in lista.pendentes()] == ["comprar ração"]


def test_concluir_ambiguo_pergunta_qual(tmp_path):
    lista = Lista(tmp_path / "t.db")
    lista.criar("comprar ração", None, "normal")
    lista.criar("pagar o boleto da internet", None, "normal")
    lista.criar("pagar o boleto do cartão", None, "normal")

    modelo = Modelo({"acao": "concluir", "busca": "boleto"})
    resposta = responder("paguei o boleto", lista, modelo, HOJE)

    assert resposta == (
        "Qual delas?\n2. pagar o boleto da internet\n3. pagar o boleto do cartão\n"
        'Responda com o número, tipo "feito 2".'
    )
    assert len(lista.pendentes()) == 3


def test_concluir_o_que_nao_existe_mostra_a_lista(tmp_path):
    lista = Lista(tmp_path / "t.db")
    lista.criar("comprar ração", None, "normal")

    modelo = Modelo({"acao": "apagar", "busca": "dentista"})
    resposta = responder("tira o dentista", lista, modelo, HOJE)

    assert resposta == (
        'Não achei essa na lista.\n1. comprar ração\nResponda com o número, tipo "apaga 1".'
    )


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Feito 2.", "Feito: pagar boleto. Faltam 1."),
        ("apaga o 1", "Tirei da lista: comprar ração. Faltam 1."),
        ("Tarefas", "Pendentes:\n1. comprar ração\n2. pagar boleto"),
    ],
)
def test_atalhos_nao_chamam_o_modelo(tmp_path, texto, esperado):
    lista = Lista(tmp_path / "t.db")
    lista.criar("comprar ração", None, "normal")
    lista.criar("pagar boleto", None, "normal")
    modelo = Modelo()

    assert responder(texto, lista, modelo, HOJE) == esperado
    assert modelo.chamadas == 0


def test_conversa_volta_none(tmp_path):
    lista = Lista(tmp_path / "t.db")
    assert responder("o que é VPN?", lista, Modelo({"acao": "conversa"}), HOJE) is None


def test_busca_vazia_do_modelo_usa_a_frase(tmp_path):
    lista = Lista(tmp_path / "t.db")
    lista.criar("levar o carro na revisão", None, "normal")
    lista.criar("renovar a CNH", None, "normal")

    modelo = Modelo({"acao": "concluir", "busca": ""})
    resposta = responder("já levei o carro na revisão", lista, modelo, HOJE)

    assert resposta == "Feito: levar o carro na revisão. Faltam 1."


def test_prazo_esquecido_pelo_modelo_sai_da_frase(tmp_path):
    lista = Lista(tmp_path / "t.db")
    resposta = responder(
        "anota: agendar dentista semana que vem", lista, criar("agendar dentista"), HOJE
    )
    assert resposta == "Anotado: agendar dentista (seg 28/09)."


def test_concluir_sem_sinal_de_feito_vira_anotacao(tmp_path):
    """'preciso responder o email' nunca pode riscar 'responder o email'."""
    lista = Lista(tmp_path / "t.db")
    lista.criar("responder o email do banco", None, "normal")
    modelo = Modelo({"acao": "concluir", "busca": "responder email banco"})

    resposta = responder("preciso responder o email do banco hoje", lista, modelo, HOJE)

    assert resposta == "Anotado: responder o email do banco hoje (hoje)."
    assert len(lista.pendentes()) == 2


def test_pedido_de_anotar_nunca_conclui(tmp_path):
    """Visto no teste de voz: o modelo leu 'marcar o dentista' como 'marca como feita'."""
    lista = Lista(tmp_path / "t.db")
    lista.criar("marcar o dentista", None, "normal")
    modelo = Modelo({"acao": "concluir", "busca": "dentista"})

    resposta = responder("Anota aí, marcar o dentista amanhã.", lista, modelo, HOJE)

    assert resposta == "Anotado: marcar o dentista amanhã (amanhã)."
    assert len(lista.pendentes()) == 2


@pytest.mark.parametrize("texto", ["concluído 1", "fiz a 1", "Feito 1!"])
def test_atalho_de_concluir_nao_passa_pela_trava(tmp_path, texto):
    lista = Lista(tmp_path / "t.db")
    lista.criar("comprar ração", None, "normal")
    assert responder(texto, lista, Modelo(), HOJE) == (
        "Feito: comprar ração. Não sobrou nada pendente."
    )


def test_desfazer(tmp_path):
    lista = Lista(tmp_path / "t.db")
    lista.criar("comprar ração", None, "normal")
    responder("x", lista, criar("pagar boleto"), HOJE)

    assert responder("desfaz", lista, Modelo(), HOJE) == (
        "Desfeito: tirei pagar boleto da lista."
    )
    responder("feito 1", lista, Modelo(), HOJE)
    assert responder("Desfazer.", lista, Modelo(), HOJE) == (
        "Desfeito: comprar ração voltou para a lista."
    )
    assert [t.titulo for t in lista.pendentes()] == ["comprar ração"]
    assert responder("desfaz", Lista(tmp_path / "vazia.db"), Modelo(), HOJE) == (
        "Não tenho nada para desfazer."
    )
