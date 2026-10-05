"""Autoriza o Akira a ler seu Gmail e Google Calendar.

Existe porque `jarvis connect gdrive` pede Client ID e Secret digitados no
terminal: ele espera o arquivo de credencial no formato próprio
(``{"client_id": ..., "client_secret": ...}``), mas o Google entrega aninhado
em ``{"installed": {...}}``. Este script converte e dispara o mesmo fluxo.

Uso (da raiz do repositório, com o OpenJarvis em ./openjarvis):
    uv run --project openjarvis python runner/conectar_google.py

Abre o navegador para você autorizar. Rode de novo se o acesso expirar
(em modo "Teste" no Google Cloud, o refresh token vence a cada 7 dias).
"""

from __future__ import annotations

import json
import sys
import webbrowser
from pathlib import Path

CRED = Path.home() / ".openjarvis" / "connectors" / "google.json"


def normalizar() -> tuple[str, str]:
    """Deixa o google.json no formato que o OpenJarvis lê, preservando tokens."""
    if not CRED.exists():
        sys.exit(
            f"Credencial não encontrada em {CRED}\n"
            "Baixe o JSON do Google Cloud (tipo 'App para computador') e salve aí."
        )

    dados = json.loads(CRED.read_text(encoding="utf-8"))

    if "installed" in dados:
        bloco = dados["installed"]
    elif "web" in dados:
        sys.exit(
            "Esta credencial é do tipo 'Aplicativo da Web'. O Akira precisa de "
            "'App para computador' — refaça no Google Cloud."
        )
    elif "client_id" in dados:
        return dados["client_id"], dados.get("client_secret", "")
    else:
        sys.exit(f"Formato de credencial não reconhecido em {CRED}")

    cid = bloco.get("client_id", "")
    secret = bloco.get("client_secret", "")
    if not cid or not secret:
        sys.exit("client_id ou client_secret ausente no arquivo do Google.")

    # Achata para o formato do OpenJarvis. Mantém o resto do dict porque é aqui
    # que os tokens de acesso vão ser gravados depois da autorização.
    plano = {k: v for k, v in dados.items() if k not in ("installed", "web")}
    plano["client_id"] = cid
    plano["client_secret"] = secret
    CRED.write_text(json.dumps(plano, indent=2), encoding="utf-8")
    print(f"credencial normalizada: {CRED}")
    return cid, secret


def main() -> int:
    cid, secret = normalizar()
    print(f"client_id: {cid[:28]}…\n")

    import openjarvis.connectors.oauth as oauth_mod
    from openjarvis.connectors.oauth import (
        get_provider_for_connector,
        run_connector_oauth,
        save_client_credentials,
    )

    # O open_browser do OpenJarvis faz `cmd /c start "" <url>` no Windows, e o
    # cmd.exe trata os "&" da query string como separador de comandos: a URL
    # chega ao navegador cortada no primeiro "&" e o Google devolve
    # "Required parameter is missing: response_type".
    # webbrowser.open passa a URL intacta. Trocado em runtime para não
    # precisar editar o repo de terceiro.
    def _abrir(url: str) -> None:
        print("\nURL de autorização (cole no navegador se ele não abrir):\n")
        print(url + "\n")
        webbrowser.open(url)

    oauth_mod.open_browser = _abrir

    provider = get_provider_for_connector("gdrive")
    if provider is None:
        sys.exit("Nenhum provider OAuth configurado para 'gdrive'.")

    save_client_credentials(provider, cid, secret)

    print("Abrindo o navegador para você autorizar…")
    print("  • escolha a sua conta Google (a mesma cadastrada como usuário de teste)")
    print("  • no aviso 'Google não verificou este app':")
    print("    Avançado → Acessar <nome do seu app> (não seguro)")
    print("  • aceite as permissões de Gmail e Calendar\n")

    try:
        run_connector_oauth("gdrive", cid, secret)
    except Exception as exc:
        print(f"\nFALHOU: {type(exc).__name__}: {exc}")
        print(
            "\nSe apareceu 'Acesso bloqueado': seu e-mail não está salvo como "
            "usuário de teste em console.cloud.google.com/auth/audience"
        )
        return 1

    print("\nAutorizado. Gmail e Calendar conectados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
