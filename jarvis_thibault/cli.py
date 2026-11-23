"""Commandes : jarvis-thibault serveur | briefing | verifier."""

from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="jarvis-thibault", description="Le Jarvis de Thibault")
    p.add_argument("--demo", action="store_true", help="utiliser des données fictives")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serveur", help="lancer le tableau de bord (http://localhost:8765)")
    s.add_argument("--port", type=int)
    s.add_argument("--ouvrir", action="store_true", help="ouvrir le navigateur")
    sub.add_parser("app", help="ouvrir Jarvis dans sa propre fenêtre (Mac)")
    sub.add_parser("moodle", help="connecter Jarvis à votre Moodle")
    sub.add_parser("bilan", help="générer le bilan du soir maintenant")
    b = sub.add_parser("briefing", help="générer le briefing maintenant")
    b.add_argument("--lire", action="store_true", help="le lire à voix haute sur le Mac")
    sub.add_parser("verifier", help="tester chaque source de données")
    a = sub.add_parser("demander", help="poser une question à Jarvis")
    a.add_argument("question", nargs="+")
    args = p.parse_args(argv)
    demo = True if args.demo else None

    if args.cmd == "serveur":
        from .serveur import demarrer

        demarrer(port=args.port, demo=demo, ouvrir=args.ouvrir)
        return 0

    if args.cmd == "moodle":
        from .connexion_moodle import connecter

        return connecter()

    if args.cmd == "app":
        from .app import main as app_main

        return app_main()

    from . import cerveau
    from .config import charger

    cfg = charger(demo=demo)

    if args.cmd == "verifier":
        d = cerveau.collecter(cfg)
        for nom in cerveau.SOURCES:
            if nom == "stripe" and not cfg["fyxigo"].get("stripe") and not cfg.demo:
                print(f"  –  {nom:8} désactivé")
            elif nom in d["erreurs"]:
                print(f"  ✗  {nom:8} {d['erreurs'][nom]}")
            else:
                print(f"  ✓  {nom:8} OK")
        print("\n--- Ce que Jarvis voit ---\n" + cerveau.contexte_texte(d, cfg))
        try:
            print("\n--- Test du cerveau ---")
            print(cerveau.generer(cfg, [{"role": "system", "content": cerveau.persona(cfg)},
                                        {"role": "user", "content": "Présente-toi en une phrase."}], 200))
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗  cerveau : {exc}")
        return 0

    if args.cmd in ("briefing", "bilan"):
        from .serveur import Etat, lancer_briefing

        b = lancer_briefing(Etat(cfg), lire_sur_mac=getattr(args, "lire", False), type_=args.cmd)
        print(b["texte"])
        if b.get("audio"):
            print(f"\n(audio : {cfg.dossier / 'audio'})")
        return 0

    if args.cmd == "demander":
        rep = cerveau.repondre(cfg, " ".join(args.question), [], cerveau.collecter(cfg))
        tache, rep = cerveau.extraire_ajout_tache(rep)
        if tache:
            from .serveur import _fichier_taches
            from .sources.taches import ajouter

            ajouter(_fichier_taches(cfg), tache)
            print(f"[tâche ajoutée : {tache}]")
        print(rep)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
