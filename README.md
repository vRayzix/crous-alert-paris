# 🏠 CROUS Alert Paris

Un bot **gratuit** qui surveille les logements CROUS et envoie une **notification push** sur le téléphone dès qu'un nouveau logement apparaît — avec le lien direct pour foncer dessus.

- **0 €** : tourne sur GitHub Actions (gratuit et illimité sur un dépôt public)
- **Pas de Telegram** : notifs via l'appli **ntfy** (gratuite, iOS + Android)
- **Pas de PC allumé** : tout tourne sur les serveurs de GitHub

> ⏰ **À savoir** : la **phase complémentaire 2026-2027 ouvre le 7 juillet à 10h**.
> Mets le bot en place **avant** pour être prévenu dès l'ouverture. Les logements
> partent parfois en moins d'une minute → une notif instantanée fait toute la différence.

---

## Comment ça marche

Toutes les 5 minutes, GitHub lance le script. Le script :
1. ouvre ta page de recherche CROUS (celle que **tu** définis, filtrée sur Paris) ;
2. compare avec la liste des logements déjà vus ;
3. envoie une notif ntfy pour chaque **nouveau** logement.

Pour compenser la limite des 5 min de GitHub, le script vérifie en réalité **plusieurs fois par exécution** (toutes les ~60 s pendant ~4 min), donc la surveillance est quasi continue.

---

## ✅ Ce qu'il te faut (5 min)

- Un compte **GitHub** (gratuit) → https://github.com
- L'appli **ntfy** :
  - iOS : « ntfy » sur l'App Store
  - Android : « ntfy » sur le Play Store (ou F-Droid)

---

## Étape 1 — Récupérer l'URL de recherche CROUS pour Paris

⚠️ **Important** : dans l'URL du CROUS, le numéro (`/tools/45/…`) correspond à la
**campagne** (année / phase), et **pas** à la ville. La ville est définie par les
coordonnées (`bounds`). Comme le numéro change selon la phase, **copie ta propre URL** :

1. Va sur **https://trouverunlogement.lescrous.fr**
2. Lance la recherche qui t'intéresse (ex. « Paris »), zoome/déplace la carte sur la
   zone voulue, puis clique sur **« Rechercher dans cette zone »**.
3. Ajoute les filtres que tu veux (type de logement, budget…).
4. **Copie l'URL** dans la barre d'adresse. Elle ressemble à :
   ```
   https://trouverunlogement.lescrous.fr/tools/45/search?bounds=2.224_48.902_2.470_48.816
   ```
   Garde-la de côté, on la colle à l'étape 4.

> 💡 Exemple de bornes pour Paris intra-muros : `bounds=2.224_48.902_2.470_48.816`
> (format = `ouest_nord_est_sud`). Élargis les valeurs pour couvrir la petite couronne.

---

## Étape 2 — Choisir un « topic » ntfy et s'abonner

1. Choisis un **nom de topic unique et difficile à deviner**, par ex.
   `crous-paris-8f3k29xz` (n'importe quoi d'aléatoire).
   > Sur ntfy.sh (gratuit), les topics sont publics : quiconque connaît le nom peut lire
   > les notifs. D'où l'intérêt d'un nom aléatoire. Il ne sera écrit **nulle part en public**
   > (on le met dans un « secret » GitHub).
2. Ouvre l'appli **ntfy** → **+** → tape exactement ce nom → **Subscribe**.
3. Garde ce nom de côté pour l'étape 4.

---

## Étape 3 — Créer le dépôt GitHub (public) et y mettre ces fichiers

1. Sur GitHub : **New repository** → nom : `crous-alert-paris` → **Public** ✅
   (public = minutes GitHub Actions **illimitées et gratuites**. En privé tu serais
   limité à 2000 min/mois, insuffisant pour tourner toutes les 5 min.)
   → **Create repository**.
2. Clone-le et ouvre-le dans VSCode :
   ```bash
   git clone https://github.com/TON_PSEUDO/crous-alert-paris.git
   cd crous-alert-paris
   ```
3. Copie **tous les fichiers de ce projet** dans le dossier (garde bien le dossier
   `.github/workflows/`).
4. Pousse sur GitHub :
   ```bash
   git add .
   git commit -m "Ajout du bot CROUS"
   git push
   ```

---

## Étape 4 — Ajouter les 2 secrets

Sur la page du dépôt GitHub :
**Settings** → **Secrets and variables** → **Actions** → **New repository secret**.

Crée ces **deux** secrets :

| Nom du secret       | Valeur                                                        |
|---------------------|--------------------------------------------------------------|
| `CROUS_SEARCH_URL`  | l'URL copiée à l'étape 1                                      |
| `NTFY_TOPIC`        | le nom de topic choisi à l'étape 2 (ex. `crous-paris-8f3k29xz`) |

---

## Étape 5 — Activer et tester

1. Onglet **Actions** du dépôt → si demandé, clique **« I understand… enable workflows »**.
2. Choisis **« Check CROUS Paris »** dans la liste de gauche → bouton **« Run workflow »**
   (déclenchement manuel) pour tester tout de suite sans attendre le prochain cron.
3. Au bout d'~1 min, ton amie devrait recevoir la notif **« ✅ Surveillance CROUS active »**.
   → si oui, tout marche ! Les prochaines notifs seront les **nouveaux** logements.

Ensuite, ça tourne tout seul toutes les 5 min. 🎉

---

## ⚠️ Limites à connaître

- **Cadence** : GitHub ne descend pas sous 5 min entre 2 lancements (et peut avoir un peu
  de retard aux heures de pointe). Le script vérifie ~1×/min pendant l'exécution, donc c'est
  quasi continu, mais tu ne choperas pas **tout** si un logement part en 30 s. Ça reste une
  énorme longueur d'avance sur une recherche manuelle.
- **Offre publique uniquement** : sans être connecté, le CROUS ne montre qu'**une partie** de
  l'offre. Pour voir **toute** l'offre liée à son profil (DSE), ton amie doit être **connectée**
  sur le site. Le bot sert donc de **signal d'alerte** (« ça bouge à Paris ! ») → elle se
  connecte alors et réserve. Pour le déclic immédiat, laisse-la connectée sur le site à côté.
- **Réserver = sur le site CROUS**, via son compte MesServices.etudiant.gouv.fr. Le bot ne
  fait que prévenir, il ne réserve pas à sa place.

---

## 🔧 Dépannage

- **Aucune notif du tout** → vérifie que le topic dans l'appli ntfy est **exactement** le même
  que le secret `NTFY_TOPIC` (sensible à la casse).
- **Le job échoue (croix rouge dans Actions)** → clique dessus pour lire les logs. Message
  « CROUS_SEARCH_URL non défini » = un secret manque ou est mal nommé.
- **« 0 logement en ligne » alors qu'il y en a** → l'URL de recherche est peut-être périmée
  (nouvelle campagne = nouveau numéro `/tools/XX/`). Recopie une URL fraîche (étape 1) et
  mets à jour le secret `CROUS_SEARCH_URL`.
- **Trop de notifs d'un coup** → normal si beaucoup de logements ouvrent en même temps ;
  au-delà de 8 nouveaux, le bot envoie une seule notif résumé.

---

## 🧪 Test en local (optionnel)

```bash
pip install -r requirements.txt

export CROUS_SEARCH_URL="https://trouverunlogement.lescrous.fr/tools/45/search?bounds=2.224_48.902_2.470_48.816"
export NTFY_TOPIC="crous-paris-8f3k29xz"
export MAX_RUNTIME=1          # une seule vérification, pour tester vite

python check_crous.py
```
