"""Importa extrato bancário (OFX ou CSV) para o banco de finanças do Akira.

Uso:
    python importar.py extrato.ofx --conta corrente
    python importar.py extrato.csv --conta cartao
    python importar.py --resumo                  # o que já foi importado

Reimportar o mesmo arquivo é seguro: o FITID do OFX identifica cada lançamento,
então duplicata é ignorada em vez de somar de novo.

Sem dependência externa: OFX é SGML e o parser aqui é proposital — as libs de
OFX brigam com as variações de cada banco, e o subconjunto que a gente precisa
(data, valor, id, descrição) é estável.
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).parent
DB = RAIZ / "financas.db"
SCHEMA = RAIZ / "schema.sql"


# ─────────────────────────────── banco ───────────────────────────────

def abrir() -> sqlite3.Connection:
    novo = not DB.exists()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    if novo:
        con.executescript(SCHEMA.read_text(encoding="utf-8"))
        con.commit()
        print(f"banco criado: {DB}")
    return con


def id_conta(con: sqlite3.Connection, apelido: str) -> int:
    row = con.execute("SELECT id FROM conta WHERE apelido = ?", (apelido,)).fetchone()
    if row:
        return row["id"]
    cur = con.execute(
        "INSERT INTO conta (apelido, instituicao) VALUES (?, ?)",
        (apelido, apelido.title()),
    )
    con.commit()
    print(f"conta '{apelido}' criada")
    return cur.lastrowid


# ─────────────────────────────── OFX ───────────────────────────────

def _tag(bloco: str, nome: str) -> str:
    """Valor de uma tag SGML do OFX (fecha por newline ou pela próxima tag)."""
    m = re.search(rf"<{nome}>([^<\r\n]*)", bloco, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _data_ofx(bruto: str) -> str:
    """OFX traz YYYYMMDDHHMMSS[.xxx][-3:GMT]. Só a data interessa."""
    d = re.sub(r"[^0-9]", "", bruto)[:8]
    if len(d) != 8:
        raise ValueError(f"data OFX inválida: {bruto!r}")
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def _centavos(bruto: str) -> int:
    """'-34.90' e '-34,90' viram -3490. Ponto flutuante não entra em dinheiro."""
    s = bruto.strip().replace(" ", "")
    if "," in s and "." in s:            # 1.234,56 (pt-BR)
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:                        # 34,90
        s = s.replace(",", ".")
    neg = s.startswith("-")
    s = s.lstrip("+-")
    inteiro, _, frac = s.partition(".")
    frac = (frac + "00")[:2]
    valor = int(inteiro or "0") * 100 + int(frac or "0")
    return -valor if neg else valor


def ler_ofx(caminho: Path) -> list[dict]:
    try:
        texto = caminho.read_text(encoding="utf-8", errors="replace")
    except UnicodeDecodeError:
        texto = caminho.read_text(encoding="latin-1", errors="replace")

    saida = []
    for bloco in re.findall(r"<STMTTRN>(.*?)</STMTTRN>", texto, re.S | re.I):
        try:
            data = _data_ofx(_tag(bloco, "DTPOSTED"))
            valor = _centavos(_tag(bloco, "TRNAMT"))
        except ValueError as e:
            print(f"  aviso: lançamento ignorado ({e})", file=sys.stderr)
            continue
        desc = _tag(bloco, "MEMO") or _tag(bloco, "NAME") or "(sem descrição)"
        saida.append({
            "data": data,
            "valor": valor,
            "descricao": desc,
            "fonte_ref": _tag(bloco, "FITID") or None,
        })

    # Saldo, quando o arquivo traz: é a âncora da conciliação.
    m = re.search(r"<LEDGERBAL>(.*?)</LEDGERBAL>", texto, re.S | re.I)
    if m:
        try:
            saida.append({
                "_saldo": True,
                "data": _data_ofx(_tag(m.group(1), "DTASOF")),
                "valor": _centavos(_tag(m.group(1), "BALAMT")),
            })
        except ValueError:
            pass
    return saida


# ─────────────────────────────── CSV ───────────────────────────────

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).strip().lower()


def ler_csv(caminho: Path) -> list[dict]:
    """CSV de banco não tem padrão. Procura as colunas pelo nome, sem acento."""
    for enc in ("utf-8-sig", "latin-1"):
        try:
            texto = caminho.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit(f"não consegui ler {caminho}")

    amostra = texto[:4096]
    try:
        sep = csv.Sniffer().sniff(amostra, delimiters=";,\t").delimiter
    except csv.Error:
        sep = ";" if amostra.count(";") > amostra.count(",") else ","

    linhas = list(csv.DictReader(texto.splitlines(), delimiter=sep))
    if not linhas:
        return []

    cols = {_norm(c): c for c in linhas[0].keys() if c}

    def achar(*termos: str) -> str | None:
        for t in termos:
            for norm, orig in cols.items():
                if t in norm:
                    return orig
        return None

    c_data = achar("data", "date")
    c_valor = achar("valor", "amount", "montante")
    c_desc = achar("descricao", "historico", "lancamento", "description", "titulo")

    if not (c_data and c_valor):
        raise SystemExit(
            f"não achei colunas de data/valor em {caminho.name}.\n"
            f"colunas: {list(linhas[0].keys())}"
        )

    saida = []
    for ln in linhas:
        bruto = (ln.get(c_data) or "").strip()
        data = None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y"):
            try:
                data = datetime.strptime(bruto, fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        if not data:
            continue
        try:
            valor = _centavos(ln.get(c_valor) or "0")
        except ValueError:
            continue
        if valor == 0:
            continue
        saida.append({
            "data": data,
            "valor": valor,
            "descricao": (ln.get(c_desc) or "(sem descrição)").strip() if c_desc else "(sem descrição)",
            # CSV raramente traz id estável; sintetiza um para não duplicar.
            "fonte_ref": f"csv:{data}:{valor}:{_norm((ln.get(c_desc) or '')[:40])}",
        })
    return saida


# ─────────────────────────── categorização ───────────────────────────

REGRAS_BASE = [
    ("IFOOD", "comida", 10), ("RAPPI", "comida", 10), ("UBER EATS", "comida", 10),
    ("RESTAURANTE", "comida", 20), ("PADARIA", "comida", 20), ("LANCHONETE", "comida", 20),
    ("MERCADO", "mercado", 20), ("SUPERMERCADO", "mercado", 15), ("ATACAD", "mercado", 20),
    ("UBER", "transporte", 30), ("99APP", "transporte", 20), ("99 ", "transporte", 30),
    ("POSTO", "transporte", 30), ("COMBUSTIVEL", "transporte", 20),
    ("NETFLIX", "assinatura", 10), ("SPOTIFY", "assinatura", 10),
    ("AMAZON PRIME", "assinatura", 10), ("YOUTUBE", "assinatura", 10),
    ("GOOGLE", "assinatura", 40), ("MICROSOFT", "assinatura", 40),
    ("OPENAI", "assinatura", 10), ("ANTHROPIC", "assinatura", 10),
    ("FARMACIA", "saude", 20), ("DROGARIA", "saude", 20),
    ("ENERGIA", "casa", 20), ("AGUA", "casa", 30), ("INTERNET", "casa", 20),
    ("ALUGUEL", "casa", 10), ("CONDOMINIO", "casa", 10),
    ("PIX ENVIADO", "transferencia", 50), ("PIX RECEBIDO", "transferencia", 50),
    ("TED", "transferencia", 50), ("SALARIO", "renda", 10),
]


def semear_regras(con: sqlite3.Connection) -> None:
    if con.execute("SELECT 1 FROM categoria_regra LIMIT 1").fetchone():
        return
    con.executemany(
        "INSERT INTO categoria_regra (padrao, categoria, prioridade) VALUES (?,?,?)",
        REGRAS_BASE,
    )
    con.commit()
    print(f"{len(REGRAS_BASE)} regras de categoria criadas")


def categorizar(con: sqlite3.Connection, descricao: str) -> str | None:
    alvo = _norm(descricao).upper()
    for r in con.execute(
        "SELECT padrao, categoria FROM categoria_regra ORDER BY prioridade, id"
    ):
        if _norm(r["padrao"]).upper() in alvo:
            return r["categoria"]
    return None


# ─────────────────────────────── main ───────────────────────────────

def importar(con: sqlite3.Connection, caminho: Path, apelido: str) -> None:
    conta = id_conta(con, apelido)
    semear_regras(con)

    itens = ler_ofx(caminho) if caminho.suffix.lower() == ".ofx" else ler_csv(caminho)
    txs = [i for i in itens if not i.get("_saldo")]
    saldos = [i for i in itens if i.get("_saldo")]

    if not txs:
        print("nenhuma transação encontrada.")
        return

    inseridas = ignoradas = 0
    for t in txs:
        cat = categorizar(con, t["descricao"])
        try:
            con.execute(
                """INSERT INTO transacao
                   (conta_id, data, valor, descricao, categoria, categoria_origem,
                    fonte, fonte_ref, confirmada)
                   VALUES (?,?,?,?,?,?,?,?,1)""",
                (conta, t["data"], t["valor"], t["descricao"], cat,
                 "regra" if cat else None,
                 caminho.suffix.lower().lstrip("."), t["fonte_ref"]),
            )
            inseridas += 1
        except sqlite3.IntegrityError:
            ignoradas += 1

    for s in saldos:
        con.execute(
            "INSERT OR REPLACE INTO saldo (conta_id, data, valor, fonte) VALUES (?,?,?,?)",
            (conta, s["data"], s["valor"], "ofx"),
        )

    datas = sorted(t["data"] for t in txs)
    con.execute(
        """INSERT INTO importacao
           (arquivo, fonte, conta_id, inseridas, ignoradas, periodo_ini, periodo_fim)
           VALUES (?,?,?,?,?,?,?)""",
        (caminho.name, caminho.suffix.lower().lstrip("."), conta,
         inseridas, ignoradas, datas[0], datas[-1]),
    )
    con.commit()

    print(f"\n{caminho.name} → conta '{apelido}'")
    print(f"  {inseridas} novas, {ignoradas} já existiam")
    print(f"  período: {datas[0]} a {datas[-1]}")
    if saldos:
        print(f"  saldo em {saldos[0]['data']}: R$ {saldos[0]['valor']/100:,.2f}")

    sem_cat = con.execute(
        "SELECT COUNT(*) c FROM transacao WHERE conta_id=? AND categoria IS NULL", (conta,)
    ).fetchone()["c"]
    if sem_cat:
        print(f"  {sem_cat} sem categoria — o modelo local classifica depois")


def resumo(con: sqlite3.Connection) -> None:
    linhas = list(con.execute(
        "SELECT mes, categoria, qtd, total_centavos FROM gasto_mensal "
        "ORDER BY mes DESC, total_centavos DESC LIMIT 40"
    ))
    if not linhas:
        print("nada importado ainda.")
        return
    mes_atual = None
    for l in linhas:
        if l["mes"] != mes_atual:
            mes_atual = l["mes"]
            total = con.execute(
                "SELECT -SUM(valor) t FROM transacao WHERE valor<0 AND substr(data,1,7)=?",
                (mes_atual,)
            ).fetchone()["t"] or 0
            print(f"\n{mes_atual}   total R$ {total/100:,.2f}")
        print(f"   {l['categoria']:<16} R$ {l['total_centavos']/100:>10,.2f}  ({l['qtd']}x)")


def main() -> int:
    p = argparse.ArgumentParser(description="Importa extrato bancário (OFX/CSV).")
    p.add_argument("arquivo", nargs="?", type=Path)
    p.add_argument("--conta", default="corrente", help="apelido da conta (corrente, cartao…)")
    p.add_argument("--resumo", action="store_true", help="mostra o que já foi importado")
    a = p.parse_args()

    con = abrir()
    try:
        if a.resumo or not a.arquivo:
            resumo(con)
        else:
            if not a.arquivo.exists():
                raise SystemExit(f"arquivo não encontrado: {a.arquivo}")
            importar(con, a.arquivo, a.conta)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
