"""Connexion guidée à Moodle (petites fenêtres sur Mac, questions dans le Terminal ailleurs)."""

from __future__ import annotations

import getpass
import platform
import re
import shutil
import subprocess

from .config import DOSSIER, charger


def _dialogue(question: str, defaut: str = "", cache: bool = False) -> str:
    if platform.system() == "Darwin" and shutil.which("osascript"):
        q = question.replace('"', "'")
        d = defaut.replace('"', "'")
        script = (f'text returned of (display dialog "{q}" default answer "{d}" '
                  f'{"with hidden answer " if cache else ""}with title "Jarvis · Moodle" '
                  'buttons {"Annuler", "OK"} default button "OK" cancel button "Annuler")')
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit("Annulé.")
        return r.stdout.strip()
    return (getpass.getpass(question + " ") if cache else input(f"{question} [{defaut}] ") or defaut).strip()


def _message(texte: str) -> None:
    print(texte)
    if platform.system() == "Darwin" and shutil.which("osascript"):
        t = texte.replace('"', "'")
        subprocess.run(["osascript", "-e", f'display dialog "{t}" with title "Jarvis · Moodle" buttons {{"OK"}} default button "OK"'],
                       capture_output=True)


def _ecrire(cle: str, valeur: str, fichier, section: str | None = None) -> None:
    s = fichier.read_text(encoding="utf-8") if fichier.exists() else ""
    if isinstance(valeur, bool):
        ligne = f"{cle} = {'true' if valeur else 'false'}"
    else:
        ligne = f'{cle} = "' + str(valeur).replace("\\", "\\\\").replace('"', '\\"') + '"'
    if section:
        bloc = re.search(rf"(?ms)^\[{re.escape(section)}\]\n(.*?)(?=^\[|\Z)", s)
        if not bloc:
            s = s.rstrip("\n") + f"\n\n[{section}]\n{ligne}\n"
        elif re.search(rf"(?m)^{cle}\s*=", bloc.group(1)):
            corps = re.sub(rf"(?m)^{cle}\s*=.*$", lambda m: ligne, bloc.group(1), count=1)
            s = s[:bloc.start(1)] + corps + s[bloc.end(1):]
        else:
            s = s[:bloc.end(1)].rstrip("\n") + f"\n{ligne}\n" + s[bloc.end(1):]
    elif re.search(rf"(?m)^{cle}\s*=", s):
        s = re.sub(rf"(?m)^{cle}\s*=.*$", lambda m: ligne, s, count=1)
    else:
        s = s.rstrip("\n") + f"\n{ligne}\n"
    fichier.write_text(s, encoding="utf-8")


def connecter() -> int:
    from .sources.moodle import donnees_moodle, jeton_depuis_identifiants

    cfg = charger()
    url = _dialogue("Adresse de votre Moodle (copiez-la depuis le navigateur, ex. https://moodle.monecole.fr) :",
                    cfg["moodle"].get("url") or "https://")
    url = url.strip().rstrip("/")
    url = re.sub(r"/(my|login|course)(/.*)?$", "", url)
    if not url.startswith("http"):
        url = "https://" + url
    mode = _dialogue("Tapez 1 pour vous connecter avec identifiant + mot de passe, ou 2 si votre école passe par une "
                     "connexion externe (ENT, Microsoft, Google…) :", "1")
    if mode.strip() == "2":
        jeton = _dialogue("Sur Moodle : avatar → Préférences → Clés de sécurité → copiez la clé « Moodle mobile web service », "
                          "puis collez-la ici :", cache=True)
    else:
        identifiant = _dialogue("Identifiant Moodle :")
        mdp = _dialogue("Mot de passe Moodle (il n'est PAS enregistré, seul un jeton est gardé) :", cache=True)
        try:
            jeton = jeton_depuis_identifiants(url, identifiant, mdp)
        except Exception as exc:  # noqa: BLE001
            _message(f"Moodle a refusé : {exc}. Si votre école passe par un ENT, relancez et choisissez 2.")
            return 1
        finally:
            mdp = ""
    try:
        d = donnees_moodle(url, jeton, cfg["moi"]["fuseau"])
    except Exception as exc:  # noqa: BLE001
        _message(f"Connexion impossible : {exc}")
        return 1
    secrets = DOSSIER / "secrets.toml"
    _ecrire("moodle_token", jeton, secrets)
    secrets.chmod(0o600)
    conf = DOSSIER / "config.toml"
    _ecrire("url", url, conf, "moodle")
    _ecrire("actif", True, conf, "moodle")
    n = len(d["devoirs"])
    _message(f"Moodle connecté ✓ ({d['site']}). {n} devoir(s) ou échéance(s) trouvés pour les 3 prochaines semaines.")
    return 0
