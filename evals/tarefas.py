"""Mede o classificador da lista de tarefas (runner/tarefas.py) contra modelos locais.

Diferente do rodar.py, o modelo não escolhe entre dez ferramentas nem calcula
data: só diz a ação e copia as palavras do prazo, que o código resolve. As
frases são outras que os exemplos do prompt, senão a nota seria de decoreba.

Uso:
    python tarefas.py                               # llama3.2:3b e qwen2.5:7b
    python tarefas.py --modelos llama3.2:3b         # só um

Sem dependências: só stdlib.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "runner"))

from tarefas import (  # noqa: E402
    _PEDIDO,
    Tarefa,
    _normalizar,
    entender,
    escolher,
    interpretar,
    resolver_prazo,
)

HOJE = date(2026, 9, 21)  # segunda, a mesma dos outros evals
PADRAO = ["llama3.2:3b", "qwen2.5:7b"]

# A lista que existe quando chegam os "já fiz" e "tira da lista".
PENDENTES = [
    Tarefa(i, titulo)
    for i, titulo in enumerate(
        [
            "levar o carro na revisão", "renovar a CNH", "mandar o relatório pro Paulo",
            "comprar presente pra minha mãe", "agendar dentista",
            "cancelar a assinatura da academia", "pagar o IPVA",
            "responder o email do banco", "trocar a lâmpada da cozinha",
            "ir no cartório", "buscar as roupas na lavanderia",
            "marcar a revisão da moto", "tomar a vacina da gripe",
        ],
        1,
    )
]  # fmt: skip

# (frase, ação esperada, checagens), conferidas como o runner usa a saída:
# titulo contém a palavra (sem acento); prazo resolve para a data (do campo ou
# da frase); prioridade igual; busca escolhe só a tarefa com a palavra.
CASOS = [
    # criar
    ("preciso levar o carro na revisão até dia 30", "criar",
     {"titulo": "carro", "prazo": date(2026, 9, 30)}),
    ("anota aí: renovar a CNH, prioridade alta", "criar",
     {"titulo": "cnh", "prioridade": "alta"}),
    ("tenho que mandar o relatório pro Paulo amanhã", "criar",
     {"titulo": "relatorio", "prazo": date(2026, 9, 22)}),
    ("me lembra de comprar presente pra minha mãe no sábado", "criar",
     {"titulo": "presente", "prazo": date(2026, 9, 26)}),
    ("Akira, anota pra mim: agendar dentista semana que vem", "criar",
     {"titulo": "dentista", "prazo": date(2026, 9, 28)}),
    ("coloca na lista cancelar a assinatura da academia", "criar",
     {"titulo": "academia"}),
    ("não posso esquecer de pagar o IPVA até o fim do mês, é urgente", "criar",
     {"titulo": "ipva", "prazo": date(2026, 9, 30), "prioridade": "alta"}),
    ("preciso responder o email do banco hoje", "criar",
     {"titulo": "banco", "prazo": HOJE}),
    ("adiciona tarefa: trocar a lâmpada da cozinha", "criar",
     {"titulo": "lampada"}),
    ("tenho que ir no cartório na quinta", "criar",
     {"titulo": "cartorio", "prazo": date(2026, 9, 24)}),
    # Transcrição do teste de voz: o modelo leu "marcar" como "marca como feita".
    ("Anota aí, marcar o dentista amanhã.", "criar",
     {"titulo": "dentista", "prazo": date(2026, 9, 22)}),
    # listar
    ("o que tem na minha lista?", "listar", {}),
    ("quais são minhas tarefas?", "listar", {}),
    ("o que ficou pendente?", "listar", {}),
    ("me mostra as tarefas", "listar", {}),
    ("tem alguma coisa pra eu fazer hoje?", "listar", {}),
    # concluir
    ("já levei o carro na revisão", "concluir", {"busca": "carro"}),
    ("paguei o IPVA", "concluir", {"busca": "ipva"}),
    ("pronto, mandei o relatório", "concluir", {"busca": "relatorio"}),
    ("consegui renovar a CNH", "concluir", {"busca": "cnh"}),
    ("terminei a da lâmpada", "concluir", {"busca": "lampada"}),
    # apagar
    ("tira da lista a academia, desisti", "apagar", {"busca": "academia"}),
    ("apaga a tarefa do cartório", "apagar", {"busca": "cartorio"}),
    ("esquece o presente da minha mãe, não precisa mais", "apagar",
     {"busca": "presente"}),
    # conversa (as armadilhas: "preciso", "tenho que" fora de tarefa)
    ("qual a capital da Austrália?", "conversa", {}),
    ("bom dia, tudo bem?", "conversa", {}),
    ("me conta uma piada", "conversa", {}),
    ("preciso de uma receita de bolo de cenoura", "conversa", {}),
    ("quanto tempo leva pra cozinhar arroz?", "conversa", {}),
    ("tenho que admitir que hoje foi um dia difícil", "conversa", {}),
    ("o que você acha de Python?", "conversa", {}),
]  # fmt: skip

# Frases escritas depois de ajustar o prompt com as de cima: a nota honesta.
NOVOS = [
    ("vou ter que buscar as roupas na lavanderia sexta", "criar",
     {"titulo": "lavanderia", "prazo": date(2026, 9, 25)}),
    ("anota: marcar a revisão da moto", "criar", {"titulo": "moto"}),
    ("me lembra de tomar a vacina da gripe dia 5", "criar",
     {"titulo": "vacina", "prazo": date(2026, 10, 5)}),
    ("falta alguma coisa na minha lista?", "listar", {}),
    ("o que eu preciso fazer essa semana?", "listar", {}),
    ("busquei as roupas na lavanderia", "concluir", {"busca": "lavanderia"}),
    ("a vacina eu já tomei", "concluir", {"busca": "vacina"}),
    ("remove a da moto, vendi ela", "apagar", {"busca": "moto"}),
    ("preciso que você me explique o que é inflação", "conversa", {}),
    ("tenho que dizer, você tá mandando bem", "conversa", {}),
]  # fmt: skip


def conferir(frase: str, saida: dict, acao: str, checagens: dict) -> list[str]:
    problemas = []
    if saida.get("acao") != acao:
        return [f"ação: esperado {acao}, veio {saida.get('acao')}"]
    for campo, esperado in checagens.items():
        valor = saida.get(campo) or ""
        if campo == "prazo":
            obtido = resolver_prazo(valor or frase, HOJE)
            if obtido != esperado:
                problemas.append(f"prazo: esperado {esperado}, veio {valor!r} -> {obtido}")
        elif campo == "prioridade":
            if valor != esperado:
                problemas.append(f"prioridade: esperado {esperado}, veio {valor!r}")
        elif campo == "busca":
            achadas = [t.titulo for t in escolher(PENDENTES, valor, frase)]
            if len(achadas) != 1 or esperado not in _normalizar(achadas[0]):
                problemas.append(f"busca {valor!r} escolheu {achadas}")
        elif esperado not in _normalizar(valor or _PEDIDO.sub("", frase)):
            problemas.append(f"{campo}: esperado conter {esperado!r}, veio {valor!r}")
    return problemas


def rodar(modelo: str) -> dict:
    print(f"\n── {modelo} " + "─" * (66 - len(modelo)))
    entender("oi", modelo)  # carrega o modelo fora da medição
    resultados = []
    casos = [(*c, False) for c in CASOS] + [(*c, True) for c in NOVOS]
    for i, (frase, acao, checagens, novo) in enumerate(casos, 1):
        inicio = time.time()
        try:
            saida = interpretar(frase, lambda texto: entender(texto, modelo))
            problemas = conferir(frase, saida, acao, checagens)
        except Exception as exc:  # noqa: BLE001
            saida, problemas = {}, [f"erro: {type(exc).__name__}: {exc}"]
        segundos = time.time() - inicio
        acao_ok = saida.get("acao") == acao
        marca = "OK" if not problemas else ("~ " if acao_ok else "X ")
        print(f"  {marca} {i:2}/{len(casos)} {segundos:5.1f}s  {frase[:52]}")
        for p in problemas:
            print(f"         → {p}")
        resultados.append(
            {"frase": frase, "esperado": acao, "saida": saida, "acao_ok": acao_ok,
             "problemas": problemas, "segundos": round(segundos, 2), "novo": novo}
        )  # fmt: skip
    return {"modelo": modelo, "resultados": resultados}


def relatorio(execucoes: list[dict]) -> None:
    print("\n" + "═" * 70)
    print(f"{'modelo':<14} {'ação':>10} {'tudo':>10} {'mediana':>9} {'p95':>7}")
    for ex in execucoes:
        r = ex["resultados"]
        n = len(r)
        acao = sum(x["acao_ok"] for x in r)
        tudo = sum(not x["problemas"] for x in r)
        tempos = sorted(x["segundos"] for x in r)
        p95 = tempos[min(n - 1, int(n * 0.95))]
        print(
            f"{ex['modelo']:<14} {acao:>3}/{n} {acao / n:4.0%} {tudo:>3}/{n} {tudo / n:4.0%}"
            f" {statistics.median(tempos):8.1f}s {p95:6.1f}s"
        )
        novos = [x for x in r if x["novo"]]
        tudo_novos = sum(not x["problemas"] for x in novos)
        print(f"{'':14} só as frases novas: {tudo_novos}/{len(novos)} certas")
        erradas = [x for x in r if not x["acao_ok"]]
        criou_sem_pedir = [x for x in erradas if x["saida"].get("acao") == "criar"]
        if criou_sem_pedir:
            print(f"{'':14} criaria tarefa sem pedido em {len(criou_sem_pedir)} frase(s)")
    print("═" * 70)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--modelos", nargs="+", default=PADRAO)
    p.add_argument("--saida", default="resultado-tarefas.json")
    a = p.parse_args()

    execucoes = [rodar(m) for m in a.modelos]
    relatorio(execucoes)
    destino = Path(__file__).parent / a.saida
    destino.write_text(json.dumps(execucoes, ensure_ascii=False, indent=2, default=str),
                       encoding="utf-8")
    print(f"\nbruto: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
