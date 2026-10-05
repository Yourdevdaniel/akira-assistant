"""40 frases em PT-BR do jeito que se fala de verdade, com o resultado esperado.

A data é fixa de propósito: "quinta às 15h" só é testável se "hoje" for determinístico.
HOJE = segunda-feira, 21 de setembro de 2026, 14:30, America/Sao_Paulo.

Matchers disponíveis em `args`:
  {"igual": "x"}       → valor exatamente igual (case-insensitive em string)
  {"prefixo": "x"}     → começa com (usado em datas: ignora segundos e timezone)
  {"contem": ["a","b"]}→ contém TODOS os termos (case-insensitive, sem acento)
  {"contem_um": [...]} → contém PELO MENOS UM dos termos
  {"presente": True}   → só precisa existir e não ser vazio

Um caso sem `args` testa apenas a escolha da ferramenta.
"""

from datetime import datetime

HOJE = datetime(2026, 9, 21, 14, 30)

_DIAS = [
    "segunda-feira", "terça-feira", "quarta-feira",
    "quinta-feira", "sexta-feira", "sábado", "domingo",
]
_MESES = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


def system_prompt() -> str:
    """Mitigação #1 da §5.1: o modelo não sabe que dia é hoje. Precisa ser dito."""
    return (
        "Você é um assistente pessoal em português do Brasil.\n"
        f"Hoje é {_DIAS[HOJE.weekday()]}, {HOJE.day} de {_MESES[HOJE.month - 1]} "
        f"de {HOJE.year}, {HOJE:%H:%M}. Fuso horário: America/Sao_Paulo (UTC-03:00).\n"
        "Use as ferramentas disponíveis para atender o pedido. Datas relativas como "
        "'amanhã', 'quinta', 'semana que vem' devem ser resolvidas a partir de hoje e "
        "escritas em ISO 8601.\n"
        "Chame exatamente uma ferramenta. Não peça confirmação, não explique."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Hoje       seg 2026-09-21      Sexta      sex 2026-09-25
# Amanhã     ter 2026-09-22      Sábado     sáb 2026-09-26
# Quarta     qua 2026-09-23      Próx. ter  ter 2026-09-29
# Quinta     qui 2026-09-24      Próx. qua  qua 2026-09-30
# ─────────────────────────────────────────────────────────────────────────────

CASOS = [
    # ── criar_evento ────────────────────────────────────────────────────────
    {
        "id": 1,
        "frase": "marca reunião com o João quinta às 15h",
        "ferramenta": "criar_evento",
        "args": {
            "titulo": {"contem_um": ["joao", "reuniao"]},
            "inicio": {"prefixo": "2026-09-24T15:00"},
        },
    },
    {
        "id": 2,
        "frase": "bota no calendário dentista amanhã de manhã às 9",
        "ferramenta": "criar_evento",
        "args": {
            "titulo": {"contem": ["dentista"]},
            "inicio": {"prefixo": "2026-09-22T09:00"},
        },
    },
    {
        "id": 3,
        "frase": "agenda um almoço com a Carla dia 3 do mês que vem meio-dia",
        "ferramenta": "criar_evento",
        "args": {
            "titulo": {"contem_um": ["almoco", "carla"]},
            "inicio": {"prefixo": "2026-10-03T12:00"},
        },
    },
    {
        "id": 4,
        "frase": "tenho consulta semana que vem terça às 8 e meia da manhã",
        "ferramenta": "criar_evento",
        "args": {
            "titulo": {"contem": ["consulta"]},
            "inicio": {"prefixo": "2026-09-29T08:30"},
        },
    },
    # ── listar_eventos ──────────────────────────────────────────────────────
    {
        "id": 5,
        "frase": "o que eu tenho amanhã?",
        "ferramenta": "listar_eventos",
        "args": {"inicio": {"prefixo": "2026-09-22"}},
    },
    {
        "id": 6,
        "frase": "me mostra minha agenda dessa semana",
        "ferramenta": "listar_eventos",
        "args": {"inicio": {"presente": True}},
    },
    {
        "id": 7,
        "frase": "tem alguma coisa marcada pra sexta?",
        "ferramenta": "listar_eventos",
        "args": {"inicio": {"prefixo": "2026-09-25"}},
    },
    {
        "id": 8,
        "frase": "quais são meus compromissos de hoje",
        "ferramenta": "listar_eventos",
        "args": {"inicio": {"prefixo": "2026-09-21"}},
    },
    # ── editar_evento ───────────────────────────────────────────────────────
    {
        "id": 9,
        "frase": "adia a reunião com o João pra sexta, mesma hora",
        "ferramenta": "editar_evento",
        "args": {
            "busca": {"contem": ["joao"]},
            "novo_inicio": {"prefixo": "2026-09-25"},
        },
    },
    {
        "id": 10,
        "frase": "muda o almoço de quinta pras 13h",
        "ferramenta": "editar_evento",
        "args": {
            "busca": {"contem": ["almoco"]},
            "novo_inicio": {"prefixo": "2026-09-24T13:00"},
        },
    },
    {
        "id": 11,
        "frase": "troca o local da reunião de amanhã pro escritório",
        "ferramenta": "editar_evento",
        "args": {"novo_local": {"contem": ["escritorio"]}},
    },
    {
        "id": 12,
        "frase": "cancela o dentista de amanhã",
        "ferramenta": "editar_evento",
        "args": {"busca": {"contem": ["dentista"]}, "cancelar": {"igual": True}},
    },
    # ── criar_tarefa ────────────────────────────────────────────────────────
    {
        "id": 13,
        "frase": "me lembra de pagar o boleto da internet até sexta",
        "ferramenta": "criar_tarefa",
        "args": {
            "titulo": {"contem": ["boleto"]},
            "prazo": {"prefixo": "2026-09-25"},
        },
    },
    {
        "id": 14,
        "frase": "preciso comprar ração pro cachorro",
        "ferramenta": "criar_tarefa",
        "args": {"titulo": {"contem": ["racao"]}},
    },
    {
        "id": 15,
        "frase": "anota aí: revisar o contrato do fornecedor, prioridade alta, até quarta",
        "ferramenta": "criar_tarefa",
        "args": {
            "titulo": {"contem": ["contrato"]},
            "prioridade": {"igual": "alta"},
            "prazo": {"prefixo": "2026-09-23"},
        },
    },
    {
        "id": 16,
        "frase": "tenho que ligar pro contador amanhã",
        "ferramenta": "criar_tarefa",
        "args": {
            "titulo": {"contem": ["contador"]},
            "prazo": {"prefixo": "2026-09-22"},
        },
    },
    # ── concluir_tarefa ─────────────────────────────────────────────────────
    {
        "id": 17,
        "frase": "já paguei o boleto da internet",
        "ferramenta": "concluir_tarefa",
        "args": {"busca": {"contem": ["boleto"]}},
    },
    {
        "id": 18,
        "frase": "terminei de revisar o contrato",
        "ferramenta": "concluir_tarefa",
        "args": {"busca": {"contem": ["contrato"]}},
    },
    {
        "id": 19,
        "frase": "marca a ração do cachorro como feita",
        "ferramenta": "concluir_tarefa",
        "args": {"busca": {"contem": ["racao"]}},
    },
    {
        "id": 20,
        "frase": "resolvi aquilo do contador",
        "ferramenta": "concluir_tarefa",
        "args": {"busca": {"contem": ["contador"]}},
    },
    # ── listar_tarefas ──────────────────────────────────────────────────────
    {
        "id": 21,
        "frase": "o que que tá pendente?",
        "ferramenta": "listar_tarefas",
    },
    {
        "id": 22,
        "frase": "quais tarefas vencem essa semana",
        "ferramenta": "listar_tarefas",
        "args": {"prazo_ate": {"presente": True}},
    },
    {
        "id": 23,
        "frase": "me mostra só as tarefas de prioridade alta",
        "ferramenta": "listar_tarefas",
        "args": {"prioridade": {"igual": "alta"}},
    },
    {
        "id": 24,
        "frase": "tem alguma coisa atrasada?",
        "ferramenta": "listar_tarefas",
        "args": {"status": {"igual": "atrasada"}},
    },
    # ── criar_nota ──────────────────────────────────────────────────────────
    {
        "id": 25,
        "frase": "anota que o Bruno falou que o prazo do projeto mudou pra novembro",
        "ferramenta": "criar_nota",
        "args": {"conteudo": {"contem": ["bruno"]}},
    },
    {
        "id": 26,
        "frase": "faz uma nota: ideia de usar o Xeon como servidor do assistente",
        "ferramenta": "criar_nota",
        "args": {"conteudo": {"contem": ["xeon"]}},
    },
    {
        "id": 27,
        "frase": "guarda isso: o wifi do escritório é rede CasaNet, canal 6",
        "ferramenta": "criar_nota",
        "args": {"conteudo": {"contem_um": ["wifi", "casanet"]}},
    },
    {
        "id": 28,
        "frase": "registra aí que a reunião com a Marina ficou de continuar semana que vem",
        "ferramenta": "criar_nota",
        "args": {"conteudo": {"contem": ["marina"]}},
    },
    # ── buscar_notas ────────────────────────────────────────────────────────
    {
        "id": 29,
        "frase": "o que eu anotei sobre o projeto do Bruno?",
        "ferramenta": "buscar_notas",
        "args": {"termo": {"contem_um": ["bruno", "projeto"]}},
    },
    {
        "id": 30,
        "frase": "procura minhas notas sobre orçamento",
        "ferramenta": "buscar_notas",
        "args": {"termo": {"contem": ["orcamento"]}},
    },
    {
        "id": 31,
        "frase": "acha aquela nota da reunião com a Marina",
        "ferramenta": "buscar_notas",
        "args": {"termo": {"contem_um": ["marina", "reuniao"]}},
    },
    {
        "id": 32,
        "frase": "eu escrevi alguma coisa sobre o Xeon?",
        "ferramenta": "buscar_notas",
        "args": {"termo": {"contem": ["xeon"]}},
    },
    # ── resumir_email ───────────────────────────────────────────────────────
    {
        "id": 33,
        "frase": "resume os emails de hoje",
        "ferramenta": "resumir_email",
        "args": {"periodo": {"presente": True}},
    },
    {
        "id": 34,
        "frase": "me fala o que chegou do Banco Exemplo",
        "ferramenta": "resumir_email",
        "args": {"remetente": {"contem": ["banco exemplo"]}},
    },
    {
        "id": 35,
        "frase": "tem algum email importante que eu não respondi?",
        "ferramenta": "resumir_email",
        "args": {"sem_resposta": {"igual": True}},
    },
    {
        "id": 36,
        "frase": "resume aquela thread com o fornecedor",
        "ferramenta": "resumir_email",
        "args": {"remetente": {"contem": ["fornecedor"]}},
    },
    # ── rascunhar_email ─────────────────────────────────────────────────────
    {
        "id": 37,
        "frase": "responde pro João que eu confirmo a reunião de quinta",
        "ferramenta": "rascunhar_email",
        "args": {"destinatario": {"contem": ["joao"]}, "corpo": {"presente": True}},
    },
    {
        "id": 38,
        "frase": "escreve um email pro contador pedindo o balanço do mês",
        "ferramenta": "rascunhar_email",
        "args": {"destinatario": {"contem": ["contador"]}, "corpo": {"presente": True}},
    },
    {
        "id": 39,
        "frase": "rascunha uma resposta pra Marina dizendo que eu vejo isso amanhã",
        "ferramenta": "rascunhar_email",
        "args": {"destinatario": {"contem": ["marina"]}},
    },
    {
        # Armadilha: "manda" não deve virar envio. Não existe ferramenta de envio —
        # §5.9 diz que email nunca sai sem confirmação humana.
        "id": 40,
        "frase": "manda um email pro fornecedor cobrando o prazo de entrega",
        "ferramenta": "rascunhar_email",
        "args": {"destinatario": {"contem": ["fornecedor"]}},
    },
]

assert len(CASOS) == 40, f"esperado 40 casos, tem {len(CASOS)}"
assert len({c["id"] for c in CASOS}) == 40, "ids duplicados"
