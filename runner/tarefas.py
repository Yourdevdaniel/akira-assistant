"""Lista de tarefas do Akira: guarda no SQLite e entende pedidos em português.

O modelo local só classifica a mensagem (criar, listar, concluir, apagar ou
conversa) num JSON com formato travado pelo Ollama. Prazo, busca e resposta
são código: o modelo erra data com cara de certa (docs/SPEC.md §5.1), e uma
resposta montada por código nunca diz "anotei" sem ter anotado.

Sem dependências: só stdlib.
"""

from __future__ import annotations

import calendar
import json
import logging
import os
import re
import sqlite3
import unicodedata
import urllib.request
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

log = logging.getLogger("akira.tarefas")

BANCO = Path.home() / ".openjarvis" / "tarefas.db"
# 127.0.0.1, não localhost: no Windows o localhost tenta IPv6 antes e perde 2 s.
OLLAMA = "http://127.0.0.1:11434/api/chat"
# O mesmo contexto que o OpenJarvis pede ao Ollama (engine/ollama.py). Com um
# valor diferente o Ollama recarrega o modelo a cada troca entre lista e
# conversa, e cada troca custa uns 10 s.
NUM_CTX = int(os.environ.get("JARVIS_NUM_CTX", "16384"))

_DIAS_SEMANA = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
_DIAS_CURTOS = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")
_NUMEROS = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5,
    "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10, "quinze": 15,
}  # fmt: skip
# Palavras que não ajudam a achar uma tarefa pela descrição, inclusive as de
# "já fiz", que vêm na frase inteira quando a busca do modelo falha.
_VAZIAS = set(
    "a o as os um uma de da do das dos pra pro pras pros para com e em no na nos "
    "nas ja aquilo aquela aquele isso isto essa esse meu minha que tarefa lista "
    "pronto feito feita fiz terminei acabei consegui tira tirar apaga apagar "
    "esquece desisti nao precisa mais akira".split()
)


@dataclass(frozen=True)
class Tarefa:
    id: int
    titulo: str
    prazo: date | None = None
    prioridade: str = "normal"


def _normalizar(texto: str) -> str:
    """Minúsculas e sem acento: 'Ração' e 'racao' são a mesma palavra."""
    decomposto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


# ── prazo ────────────────────────────────────────────────────────────────────


def resolver_prazo(frase: str, hoje: date) -> date | None:
    """'até sexta', 'amanhã', 'dia 3', '10/10', 'semana que vem' -> data.

    "Sexta" dita numa sexta é hoje: perder o prazo de hoje custa mais que ver
    a tarefa uma semana antes. "Sexta que vem" é daqui a 7 dias. Frase que não
    reconhece devolve None, nunca um chute.
    """
    t = _normalizar(frase)
    if "depois de amanha" in t:
        return hoje + timedelta(days=2)
    if "amanha" in t:
        return hoje + timedelta(days=1)
    if re.search(r"\bhoje\b", t):
        return hoje

    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if m:
        ano = int(m[3]) if m[3] else hoje.year
        ano += 2000 if ano < 100 else 0
        try:
            prazo = date(ano, int(m[2]), int(m[1]))
        except ValueError:
            return None
        if not m[3] and prazo < hoje:
            prazo = _mesmo_dia(prazo, ano + 1)
        return prazo

    m = re.search(r"\b(?:daqui a|em)\s+(\w+)\s+(dias?|semanas?)\b", t)
    if m:
        n = int(m[1]) if m[1].isdigit() else _NUMEROS.get(m[1])
        if n:
            return hoje + timedelta(days=n * (7 if m[2].startswith("semana") else 1))

    proxima_segunda = hoje + timedelta(days=7 - hoje.weekday())
    semana_que_vem = re.search(r"semana que vem|proxima semana", t)
    for indice, nome in enumerate(_DIAS_SEMANA):
        if re.search(rf"\b{nome}\b", t):
            if semana_que_vem:
                return proxima_segunda + timedelta(days=indice)
            dias = (indice - hoje.weekday()) % 7
            if dias == 0 and re.search(r"\bque vem\b|\bproxim", t):
                dias = 7
            return hoje + timedelta(days=dias)
    if semana_que_vem:
        return proxima_segunda
    if re.search(r"\bfi(?:m|nal) de semana\b|\bfds\b", t):
        return hoje + timedelta(days=(5 - hoje.weekday()) % 7)
    if re.search(r"\bfi(?:m|nal) do mes\b", t):
        return date(hoje.year, hoje.month, calendar.monthrange(hoje.year, hoje.month)[1])

    m = re.search(r"\bdia (\d{1,2}|primeiro)\b", t)
    if m:
        dia = 1 if m[1] == "primeiro" else int(m[1])
        ano, mes = hoje.year, hoje.month
        if re.search(r"mes que vem|proximo mes", t):
            ano, mes = _mes_seguinte(ano, mes)
        # "dia 3" dito no dia 25 é o do mês seguinte; "dia 31" pula mês de 30.
        for ano_mes in ((ano, mes), _mes_seguinte(ano, mes)):
            try:
                prazo = date(*ano_mes, dia)
            except ValueError:
                continue
            if prazo >= hoje:
                return prazo
    return None


def _mes_seguinte(ano: int, mes: int) -> tuple[int, int]:
    return (ano + 1, 1) if mes == 12 else (ano, mes + 1)


def _mesmo_dia(d: date, ano: int) -> date:
    try:
        return d.replace(year=ano)
    except ValueError:  # 29/02 em ano que não é bissexto
        return date(ano, 3, 1)


def quando(prazo: date | None, hoje: date) -> str:
    if prazo is None:
        return ""
    dias = (prazo - hoje).days
    rotulo = {0: "hoje", 1: "amanhã"}.get(dias)
    if rotulo is None:
        rotulo = f"{_DIAS_CURTOS[prazo.weekday()]} {prazo:%d/%m}"
    return rotulo + (", atrasada" if dias < 0 else "")


# ── resumo da manhã ──────────────────────────────────────────────────────────

_DIAS_FALADOS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
_MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
    "agosto", "setembro", "outubro", "novembro", "dezembro",
)  # fmt: skip


def _desde(prazo: date, hoje: date) -> str:
    """Como se fala o dia de um prazo que passou: 'ontem', 'terça', '3 de setembro'."""
    dias = (hoje - prazo).days
    if dias == 1:
        return "ontem"
    if dias < 7:
        return _DIAS_FALADOS[prazo.weekday()]
    return f"{prazo.day} de {_MESES[prazo.month - 1]}"


def _juntar(itens: list[str]) -> str:
    return itens[0] if len(itens) == 1 else f"{', '.join(itens[:-1])} e {itens[-1]}"


def paragrafo_do_dia(pendentes: list[Tarefa], hoje: date) -> str:
    """As tarefas que vencem hoje e as atrasadas, escritas para serem lidas em voz alta.

    Vai no fim do resumo da manhã, depois do texto do modelo. É código, e não
    o modelo, para nenhuma tarefa ficar de fora nem ganhar data errada.
    Devolve "" quando não há nada vencendo nem atrasado.
    """
    frases = []
    de_hoje = [t.titulo for t in pendentes if t.prazo == hoje]
    if de_hoje:
        frases.append(f"{'vence' if len(de_hoje) == 1 else 'vencem'} hoje: {_juntar(de_hoje)}.")
    atrasadas: dict[str, list[str]] = {}
    for tarefa in sorted((t for t in pendentes if t.prazo and t.prazo < hoje), key=lambda t: t.prazo):
        atrasadas.setdefault(_desde(tarefa.prazo, hoje), []).append(tarefa.titulo)
    for desde, titulos in atrasadas.items():
        estado = "está atrasada" if len(titulos) == 1 else "estão atrasadas"
        frases.append(f"{estado} desde {desde}: {_juntar(titulos)}.")
    if not frases:
        return ""
    primeira, *resto = frases
    return " ".join([f"Na sua lista, {primeira}", *(f[0].upper() + f[1:] for f in resto)])


# ── banco ────────────────────────────────────────────────────────────────────


class Lista:
    """Tarefas no SQLite. Abre uma conexão por operação: o worker do runner
    roda noutra thread e o sqlite3 não aceita conexão compartilhada."""

    def __init__(self, caminho: Path | None = None) -> None:
        self._caminho = caminho = caminho or BANCO
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._conectar()) as db, db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS tarefas (
                    id INTEGER PRIMARY KEY,
                    titulo TEXT NOT NULL,
                    prazo TEXT,
                    prioridade TEXT NOT NULL DEFAULT 'normal',
                    status TEXT NOT NULL DEFAULT 'pendente',
                    criada_em TEXT NOT NULL,
                    atualizada_em TEXT NOT NULL
                )"""
            )

    def _conectar(self) -> sqlite3.Connection:
        return sqlite3.connect(self._caminho)

    def criar(self, titulo: str, prazo: date | None, prioridade: str) -> Tarefa:
        agora = datetime.now().isoformat()
        with closing(self._conectar()) as db, db:
            novo_id = db.execute(
                "INSERT INTO tarefas (titulo, prazo, prioridade, criada_em, atualizada_em)"
                " VALUES (?, ?, ?, ?, ?)",
                (titulo, prazo.isoformat() if prazo else None, prioridade, agora, agora),
            ).lastrowid
        return Tarefa(novo_id, titulo, prazo, prioridade)

    def pendentes(self) -> list[Tarefa]:
        """Na ordem em que aparecem para a pessoa: é essa a numeração do 'feito 2'."""
        with closing(self._conectar()) as db:
            linhas = db.execute(
                "SELECT id, titulo, prazo, prioridade FROM tarefas"
                " WHERE status = 'pendente'"
                " ORDER BY prazo IS NULL, prazo, prioridade != 'alta', id"
            ).fetchall()
        return [
            Tarefa(i, t, date.fromisoformat(p) if p else None, pr)
            for i, t, p, pr in linhas
        ]

    def marcar(self, tarefa: Tarefa, status: str) -> None:
        """status: 'feita', 'apagada' ou 'pendente'. Nada é apagado de verdade."""
        with closing(self._conectar()) as db, db:
            db.execute(
                "UPDATE tarefas SET status = ?, atualizada_em = ? WHERE id = ?",
                (status, datetime.now().isoformat(), tarefa.id),
            )

    def desfazer(self) -> tuple[Tarefa, str] | None:
        """Desfaz a última mudança e devolve (tarefa, status novo).

        Concluída ou apagada volta a pendente; recém-criada sai da lista.
        """
        with closing(self._conectar()) as db:
            linha = db.execute(
                "SELECT id, titulo, prazo, prioridade, status, criada_em = atualizada_em"
                " FROM tarefas ORDER BY atualizada_em DESC, id DESC LIMIT 1"
            ).fetchone()
        if linha is None:
            return None
        id_, titulo, prazo, prioridade, status, recem_criada = linha
        if status != "pendente":
            novo = "pendente"
        elif recem_criada:
            novo = "apagada"
        else:
            return None
        tarefa = Tarefa(id_, titulo, date.fromisoformat(prazo) if prazo else None, prioridade)
        self.marcar(tarefa, novo)
        return tarefa, novo


# ── entender a mensagem ─────────────────────────────────────────────────────

_ESQUEMA = {
    "type": "object",
    "properties": {
        "acao": {
            "type": "string",
            "enum": ["criar", "listar", "concluir", "apagar", "conversa"],
        },
        "titulo": {"type": "string"},
        "prazo": {"type": "string"},
        "prioridade": {"type": "string", "enum": ["normal", "alta"]},
        "busca": {"type": "string"},
    },
    "required": ["acao", "titulo", "prazo", "prioridade", "busca"],
}

_INSTRUCOES = """\
Você cuida da lista de tarefas de uma pessoa. Leia a mensagem dela e responda \
só o JSON.

acao:
- criar: ela quer anotar algo que ainda vai fazer ("preciso...", "tenho que...", \
"me lembra de...", "anota...", "coloca na lista..."). O verbo da tarefa pode ser \
qualquer um, até "marcar", "cancelar" ou "apagar": continua sendo criar.
- listar: ela pergunta o que tem para fazer ou o que está pendente.
- concluir: ela conta que JÁ fez uma tarefa, com verbo no passado ("paguei...", \
"terminei...", "já liguei...") ou "feito". Sem verbo no passado não é concluir.
- apagar: ela pede para tirar uma tarefa da lista sem ter feito.
- conversa: qualquer outra coisa (perguntas, papo, pedido de informação, \
"preciso de uma dica").

titulo (só em criar): a tarefa curta, começando pelo verbo, sem o prazo.
prazo (só em criar): as palavras do prazo como ela disse ("até sexta", \
"amanhã"). Vazio se não tiver.
prioridade: "alta" só se ela disser que é urgente ou prioridade alta; senão \
"normal".
busca (em concluir e apagar): as palavras que identificam a tarefa, ou o \
número dela se ela disser um número.
Campos que não se aplicam ficam vazios."""

_EXEMPLOS = [
    ("me lembra de pagar o boleto da internet até sexta",
     {"acao": "criar", "titulo": "pagar o boleto da internet", "prazo": "até sexta",
      "prioridade": "normal", "busca": ""}),
    ("tenho que ligar pro dentista amanhã",
     {"acao": "criar", "titulo": "ligar pro dentista", "prazo": "amanhã",
      "prioridade": "normal", "busca": ""}),
    ("coloca na lista: cancelar o seguro do celular",
     {"acao": "criar", "titulo": "cancelar o seguro do celular", "prazo": "",
      "prioridade": "normal", "busca": ""}),
    ("já liguei pro contador",
     {"acao": "concluir", "titulo": "", "prazo": "", "prioridade": "normal",
      "busca": "ligar pro contador"}),
    ("paguei a conta de luz",
     {"acao": "concluir", "titulo": "", "prazo": "", "prioridade": "normal",
      "busca": "pagar a conta de luz"}),
    ("tira da lista o curso de inglês",
     {"acao": "apagar", "titulo": "", "prazo": "", "prioridade": "normal",
      "busca": "curso de inglês"}),
    ("o que eu tenho pra fazer?",
     {"acao": "listar", "titulo": "", "prazo": "", "prioridade": "normal",
      "busca": ""}),
    ("preciso de uma dica de filme",
     {"acao": "conversa", "titulo": "", "prazo": "", "prioridade": "normal",
      "busca": ""}),
    ("tenho que te contar uma coisa engraçada",
     {"acao": "conversa", "titulo": "", "prazo": "", "prioridade": "normal",
      "busca": ""}),
]  # fmt: skip


def entender(texto: str, modelo: str, url: str = OLLAMA, timeout: float = 60) -> dict:
    """Classifica a mensagem. O `format` do Ollama trava a saída no esquema."""
    mensagens = [{"role": "system", "content": _INSTRUCOES}]
    for frase, saida in _EXEMPLOS:
        mensagens.append({"role": "user", "content": frase})
        mensagens.append({"role": "assistant", "content": json.dumps(saida, ensure_ascii=False)})
    mensagens.append({"role": "user", "content": texto})
    corpo = {
        "model": modelo,
        "messages": mensagens,
        "format": _ESQUEMA,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": NUM_CTX},
    }
    pedido = urllib.request.Request(
        url, data=json.dumps(corpo).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
        return json.loads(json.loads(resposta.read())["message"]["content"])


# ── atalhos e respostas ──────────────────────────────────────────────────────

_ATALHO_LISTAR = re.compile(r"^/?(?:tarefas|lista|pendentes|pendencias)$")
_ATALHO_DESFAZER = re.compile(r"^/?(?:desfaz|desfazer|desfaca)(?: isso)?$")
_ATALHO_NUMERO = re.compile(
    r"^(feito|feita|fiz|conclui|concluida|concluido|pronto"
    r"|apaga|apagar|remove|remover|tira|tirar|exclui|excluir)"
    r"\s+(?:a |o |n(?:umero)? ?)?(\d+)$"
)
# Sinal de que a pessoa já fez: "já", "feito", verbo no passado ("paguei",
# "resolvi", "fiz"). Largo de propósito: só serve para barrar um "concluir"
# que o modelo tirou de "preciso pagar". "aí" e "aqui" terminam em i e não contam.
_JA_FEZ = re.compile(
    r"\b(?:ja|feit[oa]|pront[oa]|fiz|pus|tive|trouxe"
    r"|(?!(?:ai|aqui|ali|daqui|dali|mi|ti|si)\b)\w+(?:ei|i))\b"
)
# Começo de pedido para anotar ("anota aí, ...", "preciso ..."). Com ele o
# modelo não pode concluir nem apagar, e ele sai do título tirado da frase.
_PEDIDO = re.compile(
    r"^(?:akira[,.]?\s+)?(?:eu\s+)?"
    r"(?:preciso|tenho que|tenho de|vou ter que|n[aã]o posso esquecer de"
    r"|me lembra de|lembra de|anota(?:\s+a[ií])?(?:\s+pra mim)?|coloca na lista"
    r"|adiciona(?:\s+(?:na lista|tarefa))?)[\s:,]+",
    re.IGNORECASE,
)


def _atalho(texto: str) -> dict | None:
    """Comandos curtos resolvidos sem o modelo: 'tarefas', 'feito 2', 'desfaz'."""
    t = re.sub(r"[^\w/ ]", "", _normalizar(texto)).strip()
    if _ATALHO_LISTAR.match(t):
        return {"acao": "listar"}
    if _ATALHO_DESFAZER.match(t):
        return {"acao": "desfazer"}
    m = _ATALHO_NUMERO.match(t)
    if m:
        verbo = m[1]
        acao = "apagar" if verbo.startswith(("apag", "remov", "tir", "exclu")) else "concluir"
        return {"acao": acao, "busca": m[2]}
    return None


def _palavras(texto: str) -> set[str]:
    palavras = re.findall(r"\w+", _normalizar(texto))
    # Tira o plural para "boletos" achar "boleto".
    return {
        p[:-1] if p.endswith("s") and len(p) > 3 else p
        for p in palavras
        if p not in _VAZIAS and len(p) > 1
    }


def escolher(pendentes: list[Tarefa], busca: str, texto: str) -> list[Tarefa]:
    """A busca do modelo primeiro; se ela não achar nada, a frase inteira.

    O modelo pequeno às vezes devolve a busca vazia, e a frase da pessoa quase
    sempre tem as palavras da tarefa ("já levei o carro na revisão").
    """
    return (achar(pendentes, busca) if busca.strip() else []) or achar(pendentes, texto)


def achar(pendentes: list[Tarefa], busca: str) -> list[Tarefa]:
    """Tarefas com mais palavras em comum com a busca (empate volta todas)."""
    busca = busca.strip()
    if busca.isdigit():
        indice = int(busca) - 1
        return [pendentes[indice]] if 0 <= indice < len(pendentes) else []
    alvo = _palavras(busca)
    notas = [(len(alvo & _palavras(t.titulo)), t) for t in pendentes]
    melhor = max((n for n, _ in notas), default=0)
    return [t for n, t in notas if melhor and n == melhor]


def _descrever(tarefa: Tarefa, hoje: date) -> str:
    detalhes = [quando(tarefa.prazo, hoje)]
    if tarefa.prioridade == "alta":
        detalhes.append("prioridade alta")
    extra = ", ".join(d for d in detalhes if d)
    return tarefa.titulo + (f" ({extra})" if extra else "")


def _linha(numero: int, tarefa: Tarefa, hoje: date) -> str:
    return f"{numero}. {_descrever(tarefa, hoje)}"


def _listar(pendentes: list[Tarefa], hoje: date) -> str:
    if not pendentes:
        return "Nada pendente na sua lista."
    linhas = [_linha(i, t, hoje) for i, t in enumerate(pendentes, 1)]
    return "Pendentes:\n" + "\n".join(linhas)


def interpretar(texto: str, entender: Callable[[str], dict]) -> dict:
    """Atalho se for comando curto; senão o modelo, com a trava do concluir."""
    pedido = _atalho(texto)
    if pedido is not None:
        return pedido
    pedido = entender(texto)
    acao = pedido.get("acao")
    # O modelo pequeno às vezes lê "preciso pagar o IPVA" como "paguei" e
    # "anota aí, marcar o dentista" como "marca como feita". Riscar a tarefa
    # errada é o pior erro; anotar a mais aparece na resposta e se desfaz.
    if acao in ("concluir", "apagar") and _PEDIDO.match(texto.strip()):
        pedido = {**pedido, "acao": "criar"}
    elif acao == "concluir" and not _JA_FEZ.search(_normalizar(texto)):
        pedido = {**pedido, "acao": "criar"}
    return pedido


def responder(
    texto: str,
    lista: Lista,
    entender: Callable[[str], dict],
    hoje: date | None = None,
) -> str | None:
    """Resposta para mensagens sobre tarefas; None quando é conversa."""
    hoje = hoje or date.today()
    pedido = interpretar(texto, entender)
    acao = pedido.get("acao")
    log.info("tarefas: %s", pedido)

    if acao == "desfazer":
        desfeito = lista.desfazer()
        if desfeito is None:
            return "Não tenho nada para desfazer."
        tarefa, status = desfeito
        if status == "pendente":
            return f"Desfeito: {tarefa.titulo} voltou para a lista."
        return f"Desfeito: tirei {tarefa.titulo} da lista."

    if acao == "criar":
        titulo = (pedido.get("titulo") or _PEDIDO.sub("", texto.strip())).strip().rstrip(".")
        frase_prazo = (pedido.get("prazo") or "").strip()
        # O modelo às vezes não copia o prazo; a frase inteira ainda o tem.
        prazo = resolver_prazo(frase_prazo or texto, hoje)
        prioridade = "alta" if pedido.get("prioridade") == "alta" else "normal"
        tarefa = lista.criar(titulo, prazo, prioridade)
        resposta = f"Anotado: {_descrever(tarefa, hoje)}."
        if frase_prazo and prazo is None:
            resposta += f' Não entendi o prazo "{frase_prazo}", então ficou sem data.'
        return resposta

    if acao == "listar":
        return _listar(lista.pendentes(), hoje)

    if acao in ("concluir", "apagar"):
        pendentes = lista.pendentes()
        if not pendentes:
            return "Sua lista já está vazia."
        achadas = escolher(pendentes, pedido.get("busca") or "", texto)
        if len(achadas) != 1:
            numeros = [pendentes.index(t) + 1 for t in achadas] or range(1, len(pendentes) + 1)
            opcoes = "\n".join(_linha(n, pendentes[n - 1], hoje) for n in numeros)
            exemplo = "feito" if acao == "concluir" else "apaga"
            inicio = "Qual delas?" if achadas else "Não achei essa na lista."
            return f"{inicio}\n{opcoes}\nResponda com o número, tipo \"{exemplo} {numeros[0]}\"."
        tarefa = achadas[0]
        lista.marcar(tarefa, "feita" if acao == "concluir" else "apagada")
        restantes = len(pendentes) - 1
        inicio = "Feito" if acao == "concluir" else "Tirei da lista"
        resto = f"Faltam {restantes}." if restantes else "Não sobrou nada pendente."
        return f"{inicio}: {tarefa.titulo}. {resto}"

    return None
