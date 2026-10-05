"""As 10 ferramentas da §5.1 da spec, no formato que o Ollama espera.

Schema é contrato: mudou aqui, muda no backend. Este arquivo é a fonte da verdade
enquanto o backend não existe.
"""

FERRAMENTAS = [
    {
        "type": "function",
        "function": {
            "name": "criar_evento",
            "description": "Cria um compromisso na agenda: reunião, consulta, almoço, "
            "viagem. Use quando houver hora marcada com outras pessoas ou local.",
            "parameters": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string", "description": "Título do evento"},
                    "inicio": {
                        "type": "string",
                        "description": "Início em ISO 8601, ex: 2026-09-24T15:00",
                    },
                    "fim": {"type": "string", "description": "Fim em ISO 8601 (opcional)"},
                    "local": {"type": "string", "description": "Local (opcional)"},
                    "participantes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Nomes das pessoas envolvidas (opcional)",
                    },
                },
                "required": ["titulo", "inicio"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_eventos",
            "description": "Lista compromissos da agenda num período.",
            "parameters": {
                "type": "object",
                "properties": {
                    "inicio": {
                        "type": "string",
                        "description": "Data inicial do período, ISO 8601: 2026-09-22",
                    },
                    "fim": {
                        "type": "string",
                        "description": "Data final do período, ISO 8601: 2026-09-22",
                    },
                },
                "required": ["inicio"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "editar_evento",
            "description": "Altera um compromisso que já existe: muda horário, local, "
            "título ou cancela.",
            "parameters": {
                "type": "object",
                "properties": {
                    "busca": {
                        "type": "string",
                        "description": "Como identificar o evento, ex: 'reunião com João'",
                    },
                    "novo_inicio": {"type": "string", "description": "Novo início ISO 8601"},
                    "novo_local": {"type": "string", "description": "Novo local"},
                    "novo_titulo": {"type": "string", "description": "Novo título"},
                    "cancelar": {"type": "boolean", "description": "True para cancelar"},
                },
                "required": ["busca"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "criar_tarefa",
            "description": "Cria uma tarefa ou lembrete de algo a fazer, sem hora marcada. "
            "Use para 'preciso', 'tenho que', 'me lembra de'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string", "description": "O que precisa ser feito"},
                    "prazo": {
                        "type": "string",
                        "description": "Prazo em ISO 8601, ex: 2026-09-25 (opcional)",
                    },
                    "prioridade": {
                        "type": "string",
                        "enum": ["baixa", "media", "alta"],
                        "description": "Prioridade (opcional)",
                    },
                },
                "required": ["titulo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "concluir_tarefa",
            "description": "Marca uma tarefa existente como concluída. Use quando a pessoa "
            "disser que já fez, terminou ou resolveu algo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "busca": {
                        "type": "string",
                        "description": "Como identificar a tarefa, ex: 'boleto da internet'",
                    }
                },
                "required": ["busca"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_tarefas",
            "description": "Lista tarefas pendentes, podendo filtrar por prazo, prioridade "
            "ou atraso.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["pendente", "concluida", "atrasada"],
                        "description": "Filtro de status",
                    },
                    "prioridade": {
                        "type": "string",
                        "enum": ["baixa", "media", "alta"],
                        "description": "Filtro de prioridade",
                    },
                    "prazo_ate": {
                        "type": "string",
                        "description": "Só tarefas com prazo até esta data, ISO 8601",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "criar_nota",
            "description": "Salva uma anotação, informação ou registro para consultar "
            "depois. Use para 'anota', 'guarda', 'registra' — não é algo a fazer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "conteudo": {"type": "string", "description": "O texto da nota"},
                    "titulo": {"type": "string", "description": "Título curto (opcional)"},
                },
                "required": ["conteudo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_notas",
            "description": "Procura em notas salvas anteriormente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "termo": {"type": "string", "description": "O que procurar"}
                },
                "required": ["termo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resumir_email",
            "description": "Lê e resume emails recebidos, podendo filtrar por remetente, "
            "período ou assunto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "remetente": {"type": "string", "description": "Filtrar por remetente"},
                    "periodo": {
                        "type": "string",
                        "description": "Período, ex: hoje, semana, 2026-09-21",
                    },
                    "assunto": {"type": "string", "description": "Filtrar por assunto"},
                    "sem_resposta": {
                        "type": "boolean",
                        "description": "Só emails ainda não respondidos",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rascunhar_email",
            "description": "Escreve um rascunho de email. NUNCA envia — o rascunho sempre "
            "passa por confirmação humana antes. Use mesmo quando pedirem para 'mandar'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "destinatario": {"type": "string", "description": "Para quem"},
                    "assunto": {"type": "string", "description": "Assunto"},
                    "corpo": {"type": "string", "description": "Conteúdo da mensagem"},
                },
                "required": ["destinatario", "corpo"],
            },
        },
    },
]

NOMES = [f["function"]["name"] for f in FERRAMENTAS]
