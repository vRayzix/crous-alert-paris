# 🏠 CROUS Alert Bot

Bot **100% gratuit** qui surveille en continu les logements disponibles sur
[trouverunlogement.lescrous.fr](https://trouverunlogement.lescrous.fr) et envoie une
**notification push** sur ton téléphone dès qu'un nouveau logement apparaît — avec
le lien direct pour foncer dessus.

- **0 €** — tourne sur GitHub Actions (gratuit et illimité sur un dépôt public)
- **Aucun serveur, aucun PC à laisser allumé** — tout tourne dans le cloud GitHub
- **Aucune appli à coder** — juste des notifs via **ntfy** (gratuite, iOS + Android)
- **N'importe quelle ville** — tu configures juste la zone géographique qui t'intéresse

> ⏰ Utile toute l'année, mais **particulièrement pendant la phase complémentaire**
> (généralement en juillet), où les logements peuvent partir en moins d'une minute.
> Une notif instantanée fait toute la différence face à une recherche manuelle.

---

## Comment ça marche

```
GitHub Actions (pile toutes les heures)
        │
        ▼
check_crous.py tourne pendant ~55 minutes
   1. récupère la page de recherche CROUS (bounds = zone géographique choisie)
   2. compare avec les logements déjà vus (seen.json)
   3. si nouveau logement → notif push via ntfy.sh (avec lien direct cliquable)
   4. sauvegarde l'état immédiatement (résistant aux coupures)
│
▼
La session se termine juste avant la prochaine heure → l'heure suivante
en relance une nouvelle → couverture quasi 24h/24
```

- Le script vérifie toutes les **30 secondes**, en continu, pendant des sessions de
  **~55 minutes**, calées pile sur le déclenchement horaire suivant. Résultat :
  une surveillance quasi ininterrompue, avec seulement quelques secondes de battement
  entre deux sessions (le temps que GitHub démarre la machine suivante).
- Aucune base de données externe : l'état (« quels logements j'ai déjà vus ») est
  stocké dans un simple fichier JSON, committé automatiquement sur le dépôt — y
  compris **en cours de route**, pas seulement en fin de session, pour ne rien
  perdre en cas de coupure.
- Les notifications passent par **ntfy**, un service de push notifications open-source
  fonctionnant sur un modèle **pub/sub** (comme MQTT) : le script *publie* sur un
  "topic", et ton téléphone y est *abonné*.

---

## ⚠️ Sécurité — à lire avant de configurer

Le "topic" ntfy fonctionne exactement comme un topic MQTT sans authentification :
**c'est de la sécurité par obscurité, pas du chiffrement**.

- N'importe qui connaissant (ou devinant) le nom du topic peut **lire** tes notifs.
- N'importe qui peut aussi **publier** dessus (donc en théorie, envoyer de fausses alertes).
- Pas de compte, pas de mot de passe, pas de chiffrement de bout en bout sur l'offre
  gratuite ntfy.sh.

**Protection : choisis un nom de topic long et aléatoire**, jamais un truc devinable
(`crous-paris` tout court = mauvaise idée). Exemple correct :
`crous-a8f3k92m-x7q1`. Pour un besoin plus sérieux, deux options existent : héberger
sa propre instance ntfy, ou utiliser les topics protégés par compte (payants) de ntfy.
Pour ce cas d'usage (alertes logement, aucune donnée sensible en jeu), un nom aléatoire
suffit largement.

---

## ✅ Prérequis (5 minutes)

- Un compte **GitHub** (gratuit) → https://github.com
- L'appli **ntfy** sur ton téléphone :
  - iOS : « ntfy » sur l'App Store
  - Android : « ntfy » sur le Play Store (ou F-Droid)

---

## Étape 1 — Récupérer l'URL de recherche CROUS pour ta zone

⚠️ Dans l'URL du CROUS, le numéro (`/tools/45/…`) correspond à la **campagne**
(année / phase en cours), pas à la ville. La zone géographique est définie par les
coordonnées (`bounds`). Ce numéro change à chaque nouvelle campagne, donc **récupère
toujours ta propre URL fraîche** :

1. Va sur **https://trouverunlogement.lescrous.fr**
2. Lance une recherche, déplace/zoome la carte sur la zone qui t'intéresse, puis
   clique sur **« Rechercher dans cette zone »**.
3. Ajoute les filtres voulus (type de logement, budget…).
4. **Copie l'URL complète** dans la barre d'adresse. Elle ressemble à :
   ```
   https://trouverunlogement.lescrous.fr/tools/45/search?bounds=2.224_48.902_2.470_48.816
   ```
   Garde-la de côté pour l'étape 4.

---

## Étape 2 — Choisir un topic ntfy et s'y abonner

1. Choisis un nom de topic **long et aléatoire** (voir section Sécurité ci-dessus),
   par ex. `crous-a8f3k92m-x7q1`.
2. Ouvre l'appli **ntfy** → **+** → tape exactement ce nom → **Subscribe**.
3. Garde ce nom de côté pour l'étape 4.

---

## Étape 3 — Créer le dépôt GitHub et y déposer les fichiers

1. Sur GitHub : **New repository** → **Public** ✅ (nécessaire pour des minutes
   GitHub Actions gratuites et illimitées ; en privé, la limite de 2000 min/mois
   est vite atteinte avec des sessions de ~6h).
2. Clone-le en local :
   ```bash
   git clone https://github.com/TON_PSEUDO/NOM_DU_REPO.git
   cd NOM_DU_REPO
   ```
3. Copie tous les fichiers de ce projet dedans (en gardant bien l'arborescence
   `.github/workflows/check.yml`).
4. Pousse :
   ```bash
   git add .
   git commit -m "Ajout du bot CROUS"
   git push
   ```

---

## Étape 4 — Ajouter les 2 secrets

Sur la page du dépôt GitHub : **Settings → Secrets and variables → Actions →
New repository secret**.

| Nom du secret       | Valeur                                              |
|---------------------|------------------------------------------------------|
| `CROUS_SEARCH_URL`  | l'URL copiée à l'étape 1                              |
| `NTFY_TOPIC`        | le nom de topic choisi à l'étape 2                    |

Pense aussi à vérifier **Settings → Actions → General → Workflow permissions** →
sélectionner **« Read and write permissions »** (nécessaire pour que le bot puisse
sauvegarder son état automatiquement).

---

## Étape 5 — Activer et tester

1. Onglet **Actions** du dépôt → autoriser les workflows si demandé.
2. Sélectionne **« Check CROUS Paris »** → **Run workflow** pour tester sans
   attendre le prochain déclenchement automatique.
3. Au bout d'~1 minute, tu dois recevoir la notif **« ✅ Surveillance active »**.
   → si oui, tout fonctionne. Les prochaines notifs seront les nouveaux logements.

Ensuite ça tourne tout seul. 🎉

---

## ⚠️ Limites à connaître

- **Cadence** : le script vérifie toutes les 30 secondes en continu, mais lors
  d'affluence extrême (phase complémentaire), certains logements partent en moins
  d'une minute — impossible de tout capter à 100 %, mais c'est déjà une énorme
  longueur d'avance sur une recherche manuelle.
- **Offre publique uniquement** : sans être connecté au site avec son propre compte
  (DSE), le CROUS n'affiche qu'une partie de l'offre réelle. Le bot sert de
  **signal d'alerte** (« ça bouge dans ta zone ! ») → il faut ensuite être connecté
  sur le site pour voir l'offre complète et réserver.
- **Le bot ne réserve rien à ta place** — il notifie, la réservation se fait
  manuellement sur MesServices.etudiant.gouv.fr.

---

## 🔧 Dépannage

- **Aucune notif** → vérifie que le topic dans l'appli ntfy correspond **exactement**
  (casse comprise) au secret `NTFY_TOPIC`.
- **Le job échoue (croix rouge dans Actions)** → ouvre les logs. « CROUS_SEARCH_URL
  non défini » = secret manquant ou mal nommé.
- **« 0 logement » alors qu'il y en a** → l'URL est probablement périmée (nouvelle
  campagne = nouveau numéro `/tools/XX/`). Recopie une URL fraîche (étape 1).
- **Beaucoup de notifs d'un coup** → normal si plusieurs logements apparaissent
  simultanément ; au-delà de 8 nouveaux logements, une seule notif résumé est envoyée.

---

## 🧪 Test en local (optionnel)

```bash
pip install -r requirements.txt

export CROUS_SEARCH_URL="https://trouverunlogement.lescrous.fr/tools/45/search?bounds=2.224_48.902_2.470_48.816"
export NTFY_TOPIC="crous-a8f3k92m-x7q1"
export MAX_RUNTIME=1   # une seule vérification, pour tester vite

python check_crous.py
```

---

## Stack technique

Python · `requests` + `BeautifulSoup` pour le scraping · GitHub Actions pour
l'exécution planifiée et gratuite · ntfy pour les notifications push.
