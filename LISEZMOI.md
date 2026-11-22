# J.A.R.V.I.S. — l'assistant personnel de Thibault

Un Jarvis qui parle français, vous appelle « Monsieur » (ou « Thibault » quand le ton s'y prête), a de l'humour, et chaque matin vous fait le point à voix haute sur :

- **la météo** du jour (Open-Meteo, gratuit) ;
- **votre emploi du temps** : agendas Apple (iCloud) **et Outlook**, lus dans l'app Calendrier du Mac ;
- **les chiffres de Fyxigo** : encaissements, nouveaux clients, MRR par rapport à l'objectif, paiements échoués (Stripe), et vos indicateurs maison tirés de la base de l'appli ;
- **ce que vous devez faire pour faire avancer Fyxigo** : vos tâches (en retard et urgentes d'abord) et les 3 priorités du jour.

En plus du briefing, il y a un **tableau de bord plein écran** avec l'orbe animé, à laisser sur un écran ou une télé. Vous pouvez **lui parler au micro** (barre espace) ou lui écrire : « Combien on a encaissé cette semaine ? », « Qu'est-ce que j'ai cet après-midi ? », « Ajoute une tâche : appeler le comptable ».

Il est construit sur **OpenJarvis** et **Ollama** (l'IA tourne sur votre Mac), avec la voix d'OpenAI.

## Ce que Jarvis sait faire

**C'est une vraie app Mac** : l'icône **Jarvis** du Dock ouvre sa propre fenêtre, sans navigateur. Jarvis continue de veiller en arrière-plan même quand la fenêtre est fermée.

**Il vous parle tout seul quand il le faut :**
- le **briefing du matin** (7 h par défaut) et le **bilan du soir** (19 h 30) ;
- **10 minutes avant chaque rendez-vous** : « Monsieur, la démo Fyxigo commence dans 10 minutes, Lyon 3e. » ;
- **à chaque paiement Fyxigo** : « Ka-tching, Monsieur : 49 euros viennent de tomber. » Les nouveaux clients et les paiements échoués sont signalés aussi ;
- **vos rappels** à l'heure dite.

Chaque événement apparaît en notification en haut de l'écran et fait **flasher la zone du cerveau** qui le concerne.

**Ce que vous pouvez lui dire** (barre espace, bouton Écoute puis « Jarvis, … », ou au clavier) :

| Vous dites | Jarvis |
|---|---|
| « Fais-moi le briefing » · « Fais-moi le bilan » | lit le point complet |
| « Combien on a encaissé cette semaine ? » · « Où en est le MRR ? » | répond avec les chiffres Stripe |
| « Qu'est-ce que j'ai cet après-midi ? » | lit votre agenda |
| « Ajoute une tâche urgente : relancer le plombier » | l'ajoute aux priorités Fyxigo |
| « J'ai fini de préparer la démo » | coche la tâche |
| « Rappelle-moi à 15 h d'appeler le comptable » · « …dans 20 minutes de… » | programme un rappel vocal |
| « Souviens-toi que je préfère les rendez-vous le matin » | le retient pour toujours (et s'en sert) |
| « Qu'est-ce que je dois faire en priorité pour Fyxigo ? » | vous donne un plan d'action |
| « Qu'est-ce que j'ai à rendre cette semaine ? » · « Fais-moi le point sur mes devoirs » | compte rendu Moodle (devoirs, échéances, cours) |

**Moodle** : connectez-le une fois avec `bash ~/jarvis-thibault-main/connecter-moodle.sh` (adresse du Moodle + identifiant ; le mot de passe n'est pas gardé, seulement un jeton). Jarvis vous prévient la veille de chaque devoir à rendre.

**L'écran** : au repos, seul le cerveau est affiché. Les fenêtres (chiffres, agenda, devoirs…) apparaissent quand Jarvis en parle ou quand un événement arrive. Touche **D** ou bouton **Tableau** pour toutes les garder affichées.

**Voix George (ElevenLabs, gratuit)** : créez un compte gratuit sur elevenlabs.io, copiez votre clé (Profil → API Keys), puis `bash ~/jarvis-thibault-main/ajouter-cle.sh` → « ElevenLabs ». Jarvis prend automatiquement la voix « George ». Si le quota gratuit du mois est épuisé, il repasse tout seul sur la voix OpenAI.

**Choisir la voix** : `~/.jarvis/app/.venv/bin/jarvis-thibault voix` fait écouter 6 voix de majordome et enregistre celle que vous préférez.

**Conversation naturelle** : après chaque réponse, Jarvis se remet à l'écoute tout seul. Parlez-lui par-dessus pour le couper (ou barre espace). « Merci » ou « c'est tout » : il se remet en veille.

**Clap-clap** : même quand la fenêtre est fermée, **frappez deux fois dans vos mains** et Jarvis s'ouvre en plein écran : « À votre service, Monsieur. », puis il vous écoute : dites directement votre question. (Le micro écoute en continu : macOS affiche un point orange dans la barre des menus. Pour couper : `actif = false` dans la section `[claquement]` de `~/.jarvis/config.toml`.)

**Sur l'écran :** courbe des encaissements des 14 derniers jours, compte à rebours avant le prochain rendez-vous, état de chaque module, rappels à venir.

---

## Installation (environ 10 minutes)

1. Dézippez le dossier `jarvis-thibault`, par exemple dans *Téléchargements*.
2. Ouvrez **Terminal** (Cmd + Espace, tapez « Terminal »).
3. Tapez `bash ` (avec l'espace), **glissez le fichier `installer.sh`** dans la fenêtre, puis appuyez sur **Entrée**.
4. Répondez aux questions : ville, heure du briefing, objectif de MRR, choix du cerveau, puis vos clés.
5. Faites les **2 réglages à la main** affichés à la fin (voir ci-dessous).
6. Ouvrez l'app **Jarvis**, rangée dans le dossier *Applications* de votre dossier personnel. Jarvis démarrera ensuite tout seul à chaque ouverture de session. Au premier « Parle », macOS demande l'accès au **micro** : acceptez.

### Les clés à préparer

| Clé | Où la trouver | Pourquoi |
|---|---|---|
| OpenAI `sk-…` | https://platform.openai.com/api-keys (ajoutez 5 € de crédit) | La voix réaliste, et le cerveau si vous choisissez OpenAI |
| Stripe **restreinte** `rk_live_…` | Stripe → Développeurs → Clés API → **Créer une clé restreinte** : droits **Lecture** sur *Charges*, *Customers* et *Subscriptions* uniquement | Les chiffres de Fyxigo. La clé est en lecture seule : Jarvis ne peut rien modifier |
| Base Fyxigo `postgresql://…` | Supabase : *Project Settings → Database → Connection string* (ou l'équivalent chez votre hébergeur). Idéalement, créez un utilisateur en lecture seule | Les indicateurs de l'appli (demandes, artisans, missions…) |

Toutes les clés sont rangées dans `~/.jarvis/secrets.toml`, un fichier lisible par vous seul. Vous pouvez passer une clé avec Entrée et la remplir plus tard dans ce fichier.

### Les 2 réglages à la main

1. **Accès à l'agenda** : *Réglages Système → Confidentialité et sécurité → Accès complet au disque*, cliquez sur **+**, choisissez **Jarvis** (dans *Applications* de votre dossier personnel), puis activez l'interrupteur.
2. **Outlook dans l'agenda du Mac** : *Réglages Système → Comptes Internet → Ajouter un compte → Microsoft Exchange* (ou *Outlook.com*), puis cochez **Calendriers**. Vos rendez-vous Outlook apparaissent alors dans Calendrier, et Jarvis les voit.

---

## Au quotidien

- **Chaque matin à l'heure choisie**, Jarvis prépare le briefing, le **lit à voix haute** sur le Mac, envoie une notification et ouvre le tableau de bord. Si le Mac était éteint ou en veille, le briefing est fait au réveil, jusqu'à midi.
- **Tableau de bord** : http://localhost:8765. Le bouton **Briefing** en génère un tout de suite, **Réécouter** relit celui du jour.
- **Parler à Jarvis** : bouton micro ou **barre espace**. La dictée marche dans Chrome et Safari, qui vous demanderont l'accès au micro la première fois.
- **Vos tâches Fyxigo** sont dans `~/.jarvis/fixigo.md`. Vous pouvez les cocher sur le tableau de bord, ou dire « ajoute une tâche : … ».

  ```
  - [ ] !!! Relancer les artisans en attente @2026-11-24
  ```
  `!` à `!!!` donne la priorité, `@date` l'échéance.

## Personnaliser

Tout se règle dans `~/.jarvis/config.toml`. Quittez puis rouvrez Jarvis après une modification.

- **Appellations** : `appellations = ["Monsieur", "Thibault"]`.
- **Voix** : `voix = "onyx"`. Essayez aussi `ash`, `echo` ou `sage`. `consignes` règle le ton.
- **Cerveau** : en `ollama`, tout reste sur le Mac, gratuitement. En `openai`, il est plus fin et plus drôle, pour quelques centimes par jour, mais vos chiffres passent par OpenAI.
  > Le cerveau local doit être assez gros. Avec un petit modèle, Jarvis peut se tromper dans les chiffres. Gardez `qwen3.5:9b` si votre Mac a 16 Go ou plus. En dessous, passez à OpenAI.
- **Indicateurs de l'appli Fyxigo** : dans la section `[fixigo.base]`, mettez `active = true` et écrivez une requête SQL par indicateur. Les exemples fournis sont à adapter aux noms de vos tables.

## Commandes utiles (Terminal)

```bash
~/.jarvis/app/.venv/bin/jarvis-thibault verifier      # teste chaque source et le cerveau
~/.jarvis/app/.venv/bin/jarvis-thibault briefing --lire
~/.jarvis/app/.venv/bin/jarvis-thibault demander "Quel est mon MRR ?"
~/.jarvis/app/.venv/bin/jarvis-thibault --demo serveur --ouvrir   # essai avec des données fictives
tail -f ~/.jarvis/jarvis.log                          # journal en cas de souci
```

## En cas de souci

**Un seul réflexe : `bash ~/jarvis-thibault-main/reparer.sh`** — il arrête tout, relance la bonne version, vérifie le micro et vous dit quoi faire. Jarvis est aussi surveillé en permanence : s'il s'arrête, il est relancé tout seul dans la minute.

| Problème | Solution |
|---|---|
| L'agenda dit « introuvable ou inaccessible » | Il manque l'*Accès complet au disque* pour Jarvis (réglage 1). Si ça ne suffit pas, ajoutez aussi l'app *Terminal* |
| Pas de rendez-vous Outlook | Le compte Outlook n'est pas ajouté dans *Comptes Internet* avec « Calendriers » coché (réglage 2) |
| « Clé Stripe refusée » | Vérifiez `stripe_api_key` et les droits de lecture de la clé restreinte |
| Pas de voix | Vérifiez `openai_api_key` et votre crédit OpenAI. Sinon mettez `fournisseur = "mac"` dans `[voix]` |
| Le briefing ne se génère pas | Ollama n'est pas lancé : ouvrez l'app Ollama, ou lancez `ollama pull qwen3.5:9b` |

Pour désinstaller : `bash ~/.jarvis/app/src/desinstaller.sh`.
