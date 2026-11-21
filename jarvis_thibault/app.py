"""L'app Jarvis : une vraie fenêtre (macOS), sans navigateur, sans onglets, sans barre d'adresse.

Lancée par ~/Applications/Jarvis.app. Le serveur de Jarvis tourne à part (il continue
de veiller et de préparer le briefing même quand la fenêtre est fermée).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
import webbrowser

from .config import charger


def _serveur_repond(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1.5):
            return True
    except Exception:  # noqa: BLE001
        return False


def assurer_serveur(cfg) -> str:
    url = f"http://localhost:{cfg['serveur']['port']}/"
    if not _serveur_repond(url):
        journal = open(cfg.dossier / "jarvis.log", "ab")  # noqa: SIM115
        subprocess.Popen([sys.executable, "-m", "jarvis_thibault.cli", "serveur"],
                         stdout=journal, stderr=journal, start_new_session=True)
        for _ in range(60):
            if _serveur_repond(url):
                break
            time.sleep(0.5)
    return url


def main() -> int:
    cfg = charger()
    url = assurer_serveur(cfg)
    try:
        import webview  # pywebview : fenêtre native WebKit
    except Exception:  # noqa: BLE001
        webbrowser.open(url)
        return 0
    ecran = cfg["ecran"]
    webview.create_window(
        "J.A.R.V.I.S.", url + "?app=1",
        width=1600, height=1000, min_size=(900, 620),
        background_color="#030a2c", text_select=False,
        fullscreen=bool(ecran.get("plein_ecran", False)),
    )
    stockage = cfg.dossier / "fenetre"
    stockage.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PYWEBVIEW_LOG", "warning")
    webview.start(private_mode=False, storage_path=str(stockage))
    return 0


if __name__ == "__main__":
    sys.exit(main())
