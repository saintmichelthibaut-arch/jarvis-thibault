"""Objectifs et tâches Fixigo, dans un simple fichier Markdown (~/.jarvis/fixigo.md).

Format :

    # Objectifs
    - Atteindre 5 000 € de MRR avant fin mars

    # À faire
    - [ ] !!! Relancer les 3 artisans en attente @2026-11-21
    - [ ] !! Préparer la démo pour le salon
    - [x] Corriger le bug du paiement

« ! » = priorité (jusqu'à !!!), « @AAAA-MM-JJ » = échéance.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

_TACHE = re.compile(r"^(\s*[-*]\s+)\[( |x|X)\]\s+(.*)$")
_ECHEANCE = re.compile(r"@(\d{4}-\d{2}-\d{2})")
_PRIO = re.compile(r"^(!{1,3})\s*")


def lire(fichier: Path, aujourd_hui: Optional[date] = None) -> Dict[str, Any]:
    aujourd_hui = aujourd_hui or date.today()
    if not fichier.exists():
        return {"objectifs": [], "taches": [], "fichier": str(fichier)}
    objectifs: List[str] = []
    taches: List[Dict[str, Any]] = []
    section = ""
    for num, ligne in enumerate(fichier.read_text(encoding="utf-8").splitlines()):
        if ligne.startswith("#"):
            section = ligne.lstrip("#").strip().lower()
            continue
        m = _TACHE.match(ligne)
        if m:
            texte = m.group(3).strip()
            prio = 0
            mp = _PRIO.match(texte)
            if mp:
                prio = len(mp.group(1))
                texte = texte[mp.end():]
            ech = None
            me = _ECHEANCE.search(texte)
            if me:
                ech = me.group(1)
                texte = _ECHEANCE.sub("", texte).strip()
            en_retard = bool(ech and ech < aujourd_hui.isoformat())
            taches.append({
                "ligne": num, "texte": texte, "fait": m.group(2).lower() == "x",
                "priorite": prio, "echeance": ech, "en_retard": en_retard,
                "aujourdhui": ech == aujourd_hui.isoformat(),
            })
        elif section.startswith("objectif") and ligne.strip().startswith(("-", "*")):
            objectifs.append(ligne.strip()[1:].strip())
    taches.sort(key=lambda t: (t["fait"], not t["en_retard"], not t["aujourdhui"],
                               -t["priorite"], t["echeance"] or "9999"))
    return {"objectifs": objectifs, "taches": taches, "fichier": str(fichier)}


def basculer(fichier: Path, ligne: int) -> bool:
    lignes = fichier.read_text(encoding="utf-8").splitlines()
    if not 0 <= ligne < len(lignes):
        raise IndexError(ligne)
    m = _TACHE.match(lignes[ligne])
    if not m:
        raise ValueError("Cette ligne n'est pas une tâche")
    fait = m.group(2).lower() != "x"
    lignes[ligne] = f"{m.group(1)}[{'x' if fait else ' '}] {m.group(3)}"
    fichier.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return fait


def ajouter(fichier: Path, texte: str) -> None:
    contenu = fichier.read_text(encoding="utf-8") if fichier.exists() else "# À faire\n"
    lignes = contenu.splitlines()
    idx = next((i for i, l in enumerate(lignes) if l.lstrip("#").strip().lower().startswith("à faire")), None)
    if idx is None:
        lignes += ["", "# À faire"]
        idx = len(lignes) - 1
    lignes.insert(idx + 1, f"- [ ] {texte.strip()}")
    fichier.write_text("\n".join(lignes) + "\n", encoding="utf-8")


def taches(cfg) -> Dict[str, Any]:
    if cfg.demo:
        from .demo import FICHIER_DEMO

        return lire(FICHIER_DEMO())
    return lire(cfg.fichier_taches)
