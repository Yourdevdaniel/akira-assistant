"""Memória curta da conversa do Akira: as últimas mensagens de cada chat.

É o que deixa o modelo entender "e quantos habitantes tem lá?" depois de
"qual a capital do Canadá?". Fica só na memória do processo: reiniciar o
Akira começa uma conversa nova.

Sem dependências: só stdlib.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta

# Vai como mensagem de sistema junto com o histórico. A lista de tarefas não
# passa pelo modelo da conversa (runner/tarefas.py), e ele precisa saber disso
# para não dizer que anotou.
REGRA_DA_LISTA = (
    "Você não mexe na lista de tarefas: quem anota, lista e risca é outra parte "
    "do sistema, e ela responde por conta própria. Se a pessoa pedir para anotar "
    'algo e o pedido chegar até você, diga que não anotou e que é só mandar "anota" '
    'seguido da tarefa. Para ver a lista, ela manda "tarefas".'
)

# Resposta de conversa que finge ter mexido na lista, no formato das respostas
# de verdade de runner/tarefas.py.
_FINGE_TAREFA = re.compile(r"^\W*(anotad[oa]\b|feito:|tirei da lista|desfeito:)", re.IGNORECASE)


class Historico:
    """Últimas mensagens de cada chat, em ordem, como pares (papel, texto).

    Esquece o que passou de `validade`: o assunto da manhã não contamina a
    noite, e um modelo de 3B se perde com contexto velho.
    """

    def __init__(
        self,
        maximo: int = 10,
        validade: timedelta = timedelta(hours=2),
        agora: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._maximo = maximo
        self._validade = validade
        self._agora = agora
        self._chats: dict[str, deque[tuple[datetime, str, str]]] = {}

    def mensagens(self, chat: str) -> list[tuple[str, str]]:
        """Pares (papel, texto) ainda válidos, do mais antigo para o mais novo."""
        fila = self._chats.get(chat)
        if not fila:
            return []
        limite = self._agora() - self._validade
        while fila and fila[0][0] < limite:
            fila.popleft()
        return [(papel, texto) for _, papel, texto in fila]

    def guardar(self, chat: str, pergunta: str, resposta: str) -> None:
        fila = self._chats.setdefault(chat, deque(maxlen=self._maximo))
        agora = self._agora()
        fila.append((agora, "user", pergunta))
        fila.append((agora, "assistant", resposta))


def sem_falsa_anotacao(resposta: str) -> str:
    """Troca a resposta que finge ter mexido na lista por uma honesta."""
    if _FINGE_TAREFA.match(resposta):
        return (
            "Não mexi na sua lista: não entendi isso como tarefa. "
            'Para anotar, mande "anota" e a tarefa.'
        )
    return resposta
