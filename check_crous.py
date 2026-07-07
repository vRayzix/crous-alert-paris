#!/usr/bin/env python3
"""
Surveillance des logements CROUS + notification push via ntfy.sh

Le script :
  1. récupère la page de résultats CROUS (URL de recherche que TU fournis)
  2. compare avec les logements déjà vus (seen.json)
  3. envoie une notif ntfy pour chaque NOUVEAU logement (avec le lien direct)

Il tourne en boucle pendant ~4 min (plusieurs vérifications par exécution)
pour compenser le fait que GitHub Actions ne peut se lancer que toutes les 5 min.

Variables d'environnement :
  CROUS_SEARCH_URL  (obligatoire) l'URL de recherche copiée depuis le site CROUS
  NTFY_TOPIC        (obligatoire) le nom du "topic" ntfy auquel ton amie s'abonne
  NTFY_SERVER       (optionnel)   défaut https://ntfy.sh
  POLL_INTERVAL     (optionnel)   secondes entre 2 vérifications dans une exécution (défaut 60)
  MAX_RUNTIME       (optionnel)   durée max d'une exécution en secondes (défaut 250)
"""

import json
import os
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------- Configuration ----------
SEARCH_URL = os.environ.get("CROUS_SEARCH_URL", "").strip()
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").strip().rstrip("/")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "60"))
MAX_RUNTIME = int(os.environ.get("MAX_RUNTIME", "250"))

SEEN_FILE = Path("seen.json")
HEALTH_FILE = Path("health.json")
BASE = "https://trouverunlogement.lescrous.fr"
SUMMARY_THRESHOLD = 8  # au-delà, on envoie 1 notif résumé au lieu de spammer

# Une page qui charge normalement mais où le scraper ne trouve plus AUCUNE carte
# de logement est un signal différent d'une erreur réseau ou d'une page bloquée :
# ça sent le changement de structure HTML (ex: renommage des classes CSS par le
# CROUS). Comme une session ne dure que ~55 min, ce compteur doit survivre entre
# les sessions -> stocké dans health.json, pas juste en mémoire.
ZERO_LISTINGS_ALERT_SECONDS = 2 * 3600     # 2h de suite à 0 logement "propre" = alerte
ZERO_LISTINGS_COOLDOWN_SECONDS = 3 * 3600  # ne pas re-spammer plus souvent que ça

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}


def die(msg: str) -> None:
    print(f"ERREUR CONFIG : {msg}", file=sys.stderr)
    sys.exit(1)


class PageAnomalyError(Exception):
    """La page reçue ne ressemble pas à une vraie page CROUS.

    Signe possible : blocage IP / page de garde anti-bot (captcha, 403 stylisé
    en 200...), page de surcharge ("vous êtes trop nombreux"), ou refonte
    complète du site.
    """


# Marqueurs de contenu qui prouvent qu'on a bien une vraie page de recherche
# CROUS, QUE des logements soient trouvés ou non. Volontairement PAS basé sur
# la taille de la page : une page légitime "Aucun logement trouvé" est bien
# plus courte qu'une page pleine de résultats, et un seuil de taille fixe la
# confondrait à tort avec une vraie page de blocage/surcharge (qui, elle,
# contient même parfois le mot "crous" dans son logo/en-tête, donc un simple
# test de présence du mot ne suffit pas non plus).
GENUINE_PAGE_MARKERS = (
    "mon logement pour l'année",  # titre de la page de résultats, tous cas
    "aucun logement trouvé",       # cas 0 résultat, légitime
    "fr-card",                     # cas avec résultats : les cartes logement
)

# Marqueur explicite de la page de surcharge officielle du CROUS, pour donner
# un message d'erreur clair plutôt qu'un simple "anomalie" générique quand on
# la reconnaît précisément.
OVERLOAD_PAGE_MARKER = "vous êtes trop nombreux"


def _sanity_check_page(html: str) -> None:
    lower = html.lower()
    if OVERLOAD_PAGE_MARKER in lower:
        raise PageAnomalyError(
            "Page de surcharge officielle du CROUS (\"vous êtes trop nombreux\")."
        )
    if not any(marker in lower for marker in GENUINE_PAGE_MARKERS):
        raise PageAnomalyError(
            "Aucun marqueur de page CROUS authentique trouvé (ni résultats, "
            "ni message '0 logement' officiel) : page probablement bloquée, "
            "vide, ou site remanié."
        )


# ---------- Récupération des logements ----------
def fetch_listings() -> dict:
    """Retourne {id: {title, link, price, addr, details}} pour la recherche courante."""
    r = requests.get(SEARCH_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    # Le site CROUS sert du contenu en UTF-8, mais `requests` devine parfois mal
    # l'encodage (retombe sur Latin-1) si l'en-tête HTTP est ambigu, ce qui
    # provoque des accents cassés ("Ã©" au lieu de "é"). On force l'encodage.
    r.encoding = "utf-8"
    _sanity_check_page(r.text)
    soup = BeautifulSoup(r.text, "html.parser")

    listings = {}
    for card in soup.find_all("div", class_="fr-card"):
        link_el = card.find("a", href=True)
        if not link_el:
            continue
        href = link_el["href"]
        link = href if href.startswith("http") else BASE + href
        # identifiant = dernier segment de l'URL (l'id numérique du logement)
        key = link.rstrip("/").split("/")[-1].split("?")[0] or link

        title_el = card.find(["h3", "h2"])
        title = (title_el.get_text(strip=True) if title_el else link_el.get_text(strip=True))
        title = title or "Logement CROUS"

        price_el = card.find("p", class_="fr-badge")
        price = price_el.get_text(strip=True) if price_el else ""

        desc_el = card.find("p", class_="fr-card__desc")
        addr = desc_el.get_text(strip=True) if desc_el else ""

        details = " · ".join(
            p.get_text(strip=True) for p in card.find_all("p", class_="fr-card__detail")
        )

        listings[key] = {
            "title": title,
            "link": link,
            "price": price,
            "addr": addr,
            "details": details,
        }
    return listings


# ---------- Notifications ntfy ----------
def _ntfy_post(payload: dict) -> None:
    try:
        resp = requests.post(NTFY_SERVER, json=payload, timeout=20)
        if resp.status_code >= 300:
            print(f"  ntfy a répondu {resp.status_code} : {resp.text[:200]}")
    except Exception as e:  # noqa: BLE001
        print(f"  Échec envoi ntfy : {e}")


def notify_listing(item: dict) -> None:
    parts = [p for p in (item["price"], item["addr"], item["details"]) if p]
    msg = "\n".join(parts) if parts else "Nouveau logement disponible."
    payload = {
        "topic": NTFY_TOPIC,
        "title": f"🏠 {item['title']}"[:250],
        "message": msg[:3000],
        "priority": 5,
        "tags": ["house", "rotating_light"],
    }
    if item.get("link"):
        payload["click"] = item["link"]
    _ntfy_post(payload)


def notify_summary(n: int) -> None:
    _ntfy_post({
        "topic": NTFY_TOPIC,
        "title": f"🏠 {n} nouveaux logements CROUS !",
        "message": "Plusieurs logements viennent d'apparaître. Ouvre vite la recherche.",
        "priority": 5,
        "tags": ["house", "rotating_light"],
        "click": SEARCH_URL or BASE,
    })


def notify_start(count: int) -> None:
    _ntfy_post({
        "topic": NTFY_TOPIC,
        "title": "✅ Surveillance CROUS active",
        "message": (
            f"Bot démarré. {count} logement(s) actuellement en ligne. "
            "Tu recevras une notif dès qu'un NOUVEAU logement apparaît."
        ),
        "priority": 3,
        "tags": ["white_check_mark"],
    })


def notify_problem(kind: str, detail: str) -> None:
    _ntfy_post({
        "topic": NTFY_TOPIC,
        "title": f"⚠️ Problème de surveillance : {kind}",
        "message": (
            f"{detail}\n\nLe bot n'arrive plus à lire le site correctement depuis "
            "un moment (possible blocage ou changement du site). Vérifie "
            "manuellement le site en attendant, et regarde les logs GitHub Actions."
        ),
        "priority": 5,
        "tags": ["warning"],
    })


def notify_recovered() -> None:
    _ntfy_post({
        "topic": NTFY_TOPIC,
        "title": "✅ Surveillance rétablie",
        "message": "Le bot arrive de nouveau à lire le site normalement.",
        "priority": 3,
        "tags": ["white_check_mark"],
    })


def notify_zero_listings_stale(hours: float) -> None:
    _ntfy_post({
        "topic": NTFY_TOPIC,
        "title": "⚠️ 0 logement depuis longtemps",
        "message": (
            f"Le site répond normalement, mais le bot ne trouve plus AUCUN logement "
            f"depuis {hours:.1f}h. C'est suspect pour une grande zone comme Paris.\n\n"
            "Cause probable : le CROUS a changé la structure de sa page (le scraper "
            "doit être mis à jour) — ou, plus rarement, un vrai passage à 0 logement. "
            "Vérifie manuellement le site pour comparer."
        ),
        "priority": 5,
        "tags": ["warning"],
    })


# ---------- État persistant ----------
def load_seen():
    if SEEN_FILE.exists():
        try:
            return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
    return None


def save_seen(keys) -> None:
    SEEN_FILE.write_text(
        json.dumps(sorted(keys), ensure_ascii=False, indent=0), encoding="utf-8"
    )


def load_health() -> dict:
    """État persistant du 'streak de 0 logement', survit entre les sessions."""
    if HEALTH_FILE.exists():
        try:
            return json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"zero_since": None, "last_warned": None}


def save_health(health: dict) -> None:
    HEALTH_FILE.write_text(json.dumps(health, ensure_ascii=False), encoding="utf-8")


def commit_state() -> None:
    """Sauvegarde seen.json + health.json ET les committe/pousse tout de suite
    (best effort).

    Important quand une session dure jusqu'à ~50 min : si le job plante ou est
    tué en cours de route, on ne veut pas perdre la mémoire (ce qui provoquerait
    un flot de fausses notifs 'nouveau logement' au redémarrage, ou repartirait
    à zéro sur le suivi des anomalies). Le git config est fait en amont par le
    workflow GitHub Actions.

    Le push peut être refusé (non-fast-forward) si un AUTRE run a poussé entre-
    temps (chevauchement possible aux frontières d'une session). On gère ça
    avec un pull --rebase + nouvelle tentative, sans faire planter le script
    pour un simple conflit d'écriture sans gravité sur ce fichier d'état.
    """
    import subprocess

    try:
        paths = [str(SEEN_FILE)]
        if HEALTH_FILE.exists():
            paths.append(str(HEALTH_FILE))
        subprocess.run(["git", "add", *paths], check=True, capture_output=True)
        diff = subprocess.run(
            ["git", "diff", "--staged", "--quiet"], capture_output=True
        )
        if diff.returncode == 0:
            return  # rien à committer
        subprocess.run(
            ["git", "commit", "-m", "update state [skip ci]"],
            check=True, capture_output=True,
        )
        for attempt in range(1, 4):
            push = subprocess.run(["git", "push"], capture_output=True)
            if push.returncode == 0:
                print("  état committé/poussé.")
                return
            print(f"  push refusé (tentative {attempt}/3), pull --rebase...")
            subprocess.run(
                ["git", "pull", "--rebase", "--autostash", "origin", "main"],
                capture_output=True,
            )
        print("  (avertissement) échec du push après 3 tentatives, on continue "
              "(pas grave : au pire, un logement sera re-détecté plus tard).")
    except Exception as e:  # noqa: BLE001
        print(f"  (avertissement) échec du commit intermédiaire : {e}")


# ---------- Boucle principale ----------
# Seuils avant alerte (en nombre d'itérations consécutives ratées).
# Une anomalie de page (probable blocage / refonte du site) est un signal plus
# fort qu'une simple erreur réseau ponctuelle (timeout, hoquet de connexion) :
# on alerte donc plus vite dessus.
ANOMALY_ALERT_THRESHOLD = 3   # ~1-2 min à 30s d'intervalle
ERROR_ALERT_THRESHOLD = 6     # ~3 min à 30s d'intervalle


def main() -> None:
    if not SEARCH_URL:
        die("CROUS_SEARCH_URL non défini (voir le README).")
    if not NTFY_TOPIC:
        die("NTFY_TOPIC non défini (voir le README).")

    seen = load_seen()
    first_run = seen is None
    seen_set = set(seen or [])
    health = load_health()

    deadline = time.time() + MAX_RUNTIME
    last_listings = None
    iteration = 0

    consecutive_anomalies = 0
    consecutive_errors = 0
    last_anomaly_reason = ""
    last_error_reason = ""
    # Persisté dans health.json (pas juste en mémoire) : sinon, si l'alerte part
    # vers la fin d'une session et que le site se rétablit dans la session
    # SUIVANTE (nouveau process, donc mémoire vidée), on "oublie" qu'il fallait
    # prévenir du rétablissement, et la notif "✅ rétabli" ne part jamais.
    alerted_this_run = bool(health.get("network_alerted"))

    while True:
        iteration += 1
        stamp = time.strftime("%H:%M:%S")
        listings = None
        try:
            listings = fetch_listings()
        except PageAnomalyError as e:
            consecutive_anomalies += 1
            consecutive_errors = 0
            last_anomaly_reason = str(e)
            print(f"[{stamp}] iter {iteration} : ANOMALIE page ({e}) "
                  f"[{consecutive_anomalies}/{ANOMALY_ALERT_THRESHOLD}]")
        except Exception as e:  # noqa: BLE001
            consecutive_errors += 1
            consecutive_anomalies = 0
            last_error_reason = str(e)
            print(f"[{stamp}] iter {iteration} : échec de la récupération ({e}) "
                  f"[{consecutive_errors}/{ERROR_ALERT_THRESHOLD}]")

        if listings is not None:
            # Une récupération réussie : si on avait alerté (et que ce n'est pas le
            # tout premier démarrage), on prévient que c'est réglé. Sur un premier
            # démarrage, le message "Surveillance active" suffit, pas besoin d'un
            # "rétabli" qui n'aurait rien à raconter de sensé avant lui.
            if alerted_this_run and not first_run:
                notify_recovered()
            alerted_this_run = False
            health["network_alerted"] = False
            save_health(health)
            commit_state()
            consecutive_anomalies = 0
            consecutive_errors = 0

            last_listings = listings
            if first_run:
                # Premier lancement : on mémorise sans spammer les logements déjà là
                seen_set = set(listings.keys())
                notify_start(len(listings))
                first_run = False
                print(f"[{stamp}] iter {iteration} : état initial "
                      f"({len(listings)} logement(s)) mémorisé, pas de notif de listing.")
            else:
                # Suivi du "streak de 0 logement propre" (page OK mais aucune carte
                # trouvée) : signal distinct d'un simple 0 nouveau, plus révélateur
                # d'un changement de structure du site que d'un vrai manque d'offre.
                now = time.time()
                if len(listings) == 0:
                    if health.get("zero_since") is None:
                        health["zero_since"] = now
                        save_health(health)
                        commit_state()
                    duration = now - health["zero_since"]
                    last_warned = health.get("last_warned")
                    if duration >= ZERO_LISTINGS_ALERT_SECONDS and (
                        last_warned is None
                        or (now - last_warned) >= ZERO_LISTINGS_COOLDOWN_SECONDS
                    ):
                        notify_zero_listings_stale(duration / 3600)
                        health["last_warned"] = now
                        save_health(health)
                        commit_state()
                elif health.get("zero_since") is not None:
                    # Ça repart : si on avait alerté, on prévient que c'est réglé.
                    if health.get("last_warned") is not None:
                        notify_recovered()
                    health["zero_since"] = None
                    health["last_warned"] = None
                    save_health(health)
                    commit_state()

                new = [k for k in listings if k not in seen_set]
                if new:
                    print(f"[{stamp}] iter {iteration} : {len(new)} NOUVEAU(X) !")
                    if len(new) > SUMMARY_THRESHOLD:
                        notify_summary(len(new))
                    else:
                        for k in new:
                            print(f"    -> {listings[k]['title']} ({listings[k]['link']})")
                            notify_listing(listings[k])
                    seen_set |= set(new)
                    # On persiste l'état courant (comme la sauvegarde finale) et pas le
                    # cumul de la boucle, pour qu'un logement libéré à nouveau après un
                    # crash re-déclenche bien une notif au prochain démarrage.
                    save_seen(listings.keys())
                    commit_state()
                else:
                    print(f"[{stamp}] iter {iteration} : rien de nouveau "
                          f"({len(listings)} en ligne)")
        else:
            # Échec de récupération : on alerte une seule fois par session si le
            # problème persiste, pour ne pas spammer à chaque itération.
            if not alerted_this_run:
                if consecutive_anomalies >= ANOMALY_ALERT_THRESHOLD:
                    notify_problem(
                        "page suspecte",
                        f"{consecutive_anomalies} vérifications de suite ont détecté "
                        f"une page anormale.\n\nRaison précise : {last_anomaly_reason}",
                    )
                    alerted_this_run = True
                    health["network_alerted"] = True
                    save_health(health)
                    commit_state()
                elif consecutive_errors >= ERROR_ALERT_THRESHOLD:
                    notify_problem(
                        "erreurs réseau répétées",
                        f"{consecutive_errors} tentatives de suite ont échoué.\n\n"
                        f"Raison précise : {last_error_reason}",
                    )
                    alerted_this_run = True
                    health["network_alerted"] = True
                    save_health(health)
                    commit_state()

        # Fin de la fenêtre de temps ?
        if time.time() + POLL_INTERVAL >= deadline:
            break
        time.sleep(POLL_INTERVAL)

    # On persiste l'état de la DERNIÈRE vue (les logements disparus ressortent
    # de la liste => ils re-notifieront s'ils réapparaissent, ce qui est voulu).
    if last_listings is not None:
        save_seen(last_listings.keys())
        print(f"État sauvegardé : {len(last_listings)} logement(s) suivis.")
    else:
        print("Aucune récupération réussie durant cette exécution : état inchangé.")


if __name__ == "__main__":
    main()
