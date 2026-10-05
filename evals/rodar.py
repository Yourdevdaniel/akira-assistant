"""Mede tool calling em PT-BR contra modelos locais no Ollama.

Responde três perguntas da spec de uma vez:
  1. O Qwen local acerta ferramenta e argumentos em português? (§5.1, risco R1)
  2. Qual modelo? qwen3:4b tem latência de ligação, o 8b tem qualidade (§4)
  3. A latência fecha o orçamento do modo ligação? (§5.2)

Uso:
    python rodar.py                        # 4b e 8b, sem thinking
    python rodar.py --modelos qwen3:8b     # só um
    python rodar.py --think                # com thinking do qwen3 (mais lento)
    python rodar.py --falhas               # detalha cada erro

Sem dependências: só stdlib.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from casos import CASOS, system_prompt  # noqa: E402
from ferramentas import FERRAMENTAS  # noqa: E402

OLLAMA = "http://localhost:11434/api/chat"
PADRAO = ["qwen3:4b", "qwen3:8b"]
TIMEOUT = 180


# ── comparação ───────────────────────────────────────────────────────────────


def normalizar(v) -> str:
    """Minúsculas, sem acento — 'Reunião' e 'reuniao' são a mesma coisa."""
    s = str(v).lower()
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def casa(valor, matcher: dict) -> bool:
    if valor is None or valor == "" or valor == []:
        return False
    if "presente" in matcher:
        return True
    if "igual" in matcher:
        esperado = matcher["igual"]
        if isinstance(esperado, bool):
            return valor is True if esperado else valor is False
        return normalizar(valor) == normalizar(esperado)
    if "prefixo" in matcher:
        return normalizar(valor).startswith(normalizar(matcher["prefixo"]))
    if "contem" in matcher:
        alvo = normalizar(valor)
        return all(normalizar(t) in alvo for t in matcher["contem"])
    if "contem_um" in matcher:
        alvo = normalizar(valor)
        return any(normalizar(t) in alvo for t in matcher["contem_um"])
    raise ValueError(f"matcher desconhecido: {matcher}")


def conferir(caso: dict, nome: str | None, args: dict) -> tuple[bool, bool, list[str]]:
    """→ (ferramenta_ok, args_ok, lista de problemas)"""
    ferramenta_ok = nome == caso["ferramenta"]
    if not ferramenta_ok:
        return False, False, [f"ferramenta: esperado {caso['ferramenta']}, veio {nome}"]

    problemas = []
    for campo, matcher in caso.get("args", {}).items():
        if not casa(args.get(campo), matcher):
            problemas.append(f"{campo}: esperado {matcher}, veio {args.get(campo)!r}")
    return True, not problemas, problemas


# ── execução ─────────────────────────────────────────────────────────────────


def chamar(modelo: str, frase: str, think: bool) -> tuple[str | None, dict, float, str]:
    """→ (nome_ferramenta, args, segundos, erro)"""
    payload = {
        "model": modelo,
        "messages": [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": frase},
        ],
        "tools": FERRAMENTAS,
        "stream": False,
        "think": think,
        "options": {"temperature": 0, "num_ctx": 4096},
    }
    req = urllib.request.Request(
        OLLAMA,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            corpo = json.loads(r.read())
    except urllib.error.URLError as e:
        return None, {}, time.perf_counter() - t0, f"rede: {e}"
    except Exception as e:  # noqa: BLE001
        return None, {}, time.perf_counter() - t0, f"{type(e).__name__}: {e}"

    dt = time.perf_counter() - t0
    chamadas = corpo.get("message", {}).get("tool_calls") or []
    if not chamadas:
        texto = (corpo.get("message", {}).get("content") or "").strip()
        return None, {}, dt, f"nenhuma ferramenta chamada (respondeu texto: {texto[:60]!r})"

    fn = chamadas[0].get("function", {})
    args = fn.get("arguments") or {}
    if isinstance(args, str):  # alguns builds devolvem JSON como string
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return fn.get("name"), args, dt, ""


def rodar(modelo: str, think: bool, limite: int = 0) -> dict:
    casos = CASOS[:limite] if limite else CASOS
    corte = f"  [{len(casos)} de {len(CASOS)} casos]" if limite else ""
    print(f"\n{'─' * 70}\n{modelo}  (thinking: {'on' if think else 'off'}){corte}\n{'─' * 70}")
    resultados = []
    for i, caso in enumerate(casos, 1):
        nome, args, dt, erro = chamar(modelo, caso["frase"], think)
        ferramenta_ok, args_ok, problemas = conferir(caso, nome, args)
        if erro and nome is None:
            problemas = [erro]
        resultados.append(
            {
                "id": caso["id"],
                "frase": caso["frase"],
                "esperado": caso["ferramenta"],
                "veio": nome,
                "args": args,
                "ferramenta_ok": ferramenta_ok,
                "args_ok": args_ok,
                "problemas": problemas,
                "segundos": round(dt, 2),
            }
        )
        marca = "OK " if args_ok else ("~  " if ferramenta_ok else "X  ")
        print(f"  {marca}{i:2}/40  {dt:5.1f}s  {caso['frase'][:52]}")

    return {"modelo": modelo, "think": think, "resultados": resultados}


# ── relatório ────────────────────────────────────────────────────────────────


def relatorio(execucoes: list[dict], detalhar: bool) -> None:
    print(f"\n{'═' * 70}\nRESULTADO\n{'═' * 70}\n")
    print(f"{'modelo':<14} {'ferramenta':>11} {'+ args':>9} {'mediana':>9} {'p95':>8}")
    print(f"{'-' * 14} {'-' * 11} {'-' * 9} {'-' * 9} {'-' * 8}")

    for ex in execucoes:
        rs = ex["resultados"]
        n = len(rs)
        f_ok = sum(r["ferramenta_ok"] for r in rs)
        a_ok = sum(r["args_ok"] for r in rs)
        tempos = sorted(r["segundos"] for r in rs)
        mediana = tempos[n // 2]
        p95 = tempos[min(int(n * 0.95), n - 1)]
        print(
            f"{ex['modelo']:<14} {f_ok:>4}/{n} {100 * f_ok / n:>4.0f}% "
            f"{a_ok:>3} {100 * a_ok / n:>3.0f}% {mediana:>8.1f}s {p95:>7.1f}s"
        )

    # Por ferramenta — onde exatamente ele erra
    print(f"\n{'ferramenta':<18}", end="")
    for ex in execucoes:
        print(f"{ex['modelo']:>12}", end="")
    print()
    print("-" * (18 + 12 * len(execucoes)))
    for nome in dict.fromkeys(c["ferramenta"] for c in CASOS):
        print(f"{nome:<18}", end="")
        for ex in execucoes:
            rs = [r for r in ex["resultados"] if r["esperado"] == nome]
            ok = sum(r["args_ok"] for r in rs)
            print(f"{ok:>7}/{len(rs)}  ", end="")
        print()

    if detalhar:
        for ex in execucoes:
            falhas = [r for r in ex["resultados"] if not r["args_ok"]]
            if not falhas:
                continue
            print(f"\n{'─' * 70}\nFALHAS — {ex['modelo']}\n{'─' * 70}")
            for r in falhas:
                print(f"\n  #{r['id']}  {r['frase']}")
                for p in r["problemas"]:
                    print(f"       → {p}")

    # Veredito contra o critério da spec (§5.1: 90%)
    print(f"\n{'═' * 70}")
    for ex in execucoes:
        rs = ex["resultados"]
        taxa = 100 * sum(r["args_ok"] for r in rs) / len(rs)
        mediana = sorted(r["segundos"] for r in rs)[len(rs) // 2]
        if taxa >= 90:
            v = "APROVADO — serve pra produção"
        elif taxa >= 75:
            v = "LIMÍTROFE — precisa do parser de data (§5.1 mitigação 2)"
        else:
            v = "REPROVADO — ver §9 (upgrade de RAM / modelo maior)"
        voz = "cabe no modo ligação" if mediana <= 2.0 else "lento pra ligação"
        print(f"  {ex['modelo']:<12} {taxa:5.1f}%  {v}")
        print(f"  {'':12} mediana {mediana:.1f}s — {voz}")
    print("═" * 70)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--modelos", nargs="+", default=PADRAO)
    p.add_argument("--think", action="store_true", help="liga o thinking do qwen3")
    p.add_argument("--falhas", action="store_true", help="detalha cada erro")
    p.add_argument("--saida", default="resultado.json")
    p.add_argument(
        "--limite",
        type=int,
        default=0,
        metavar="N",
        help="roda só os N primeiros casos (comparação rápida entre modelos)",
    )
    a = p.parse_args()

    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5)
    except Exception:  # noqa: BLE001
        print("Ollama não respondeu em localhost:11434. Rode `ollama serve` primeiro.")
        return 1

    execucoes = [rodar(m, a.think, a.limite) for m in a.modelos]
    relatorio(execucoes, a.falhas)

    destino = Path(__file__).parent / a.saida
    destino.write_text(json.dumps(execucoes, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nbruto: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
