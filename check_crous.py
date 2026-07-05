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
BASE = "https://trouverunlogement.lescrous.fr"
SUMMARY_THRESHOLD = 8  # au-delà, on envoie 1 notif résumé au lieu de spammer

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


# ---------- Récupération des logements ----------
def fetch_listings() -> dict:
    """Retourne {id: {title, link, price, addr, details}} pour la recherche courante."""
    r = requests.get(SEARCH_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    # Le site CROUS sert du contenu en UTF-8, mais `requests` devine parfois mal
    # l'encodage (retombe sur Latin-1) si l'en-tête HTTP est ambigu, ce qui
    # provoque des accents cassés ("Ã©" au lieu de "é"). On force l'encodage.
    r.encoding = "utf-8"
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


def commit_state() -> None:
    """Sauvegarde seen.json ET le committe/pousse tout de suite (best effort).

    Important quand une exécution dure ~6h : si le job plante ou est tué en
    cours de route, on ne veut pas perdre des heures de mémoire (ce qui
    provoquerait un flot de fausses notifs 'nouveau logement' au redémarrage).
    Le script git config est fait en amont par le workflow GitHub Actions.
    """
    import subprocess

    try:
        subprocess.run(["git", "add", "seen.json"], check=True, capture_output=True)
        diff = subprocess.run(
            ["git", "diff", "--staged", "--quiet"], capture_output=True
        )
        if diff.returncode == 0:
            return  # rien à committer
        subprocess.run(
            ["git", "commit", "-m", "update state [skip ci]"],
            check=True, capture_output=True,
        )
        subprocess.run(["git", "push"], check=True, capture_output=True)
        print("  état committé/poussé.")
    except Exception as e:  # noqa: BLE001
        print(f"  (avertissement) échec du commit intermédiaire : {e}")


# ---------- Boucle principale ----------
def main() -> None:
    if not SEARCH_URL:
        die("CROUS_SEARCH_URL non défini (voir le README).")
    if not NTFY_TOPIC:
        die("NTFY_TOPIC non défini (voir le README).")

    seen = load_seen()
    first_run = seen is None
    seen_set = set(seen or [])

    deadline = time.time() + MAX_RUNTIME
    last_listings = None
    iteration = 0

    while True:
        iteration += 1
        stamp = time.strftime("%H:%M:%S")
        try:
            listings = fetch_listings()
        except Exception as e:  # noqa: BLE001
            print(f"[{stamp}] iter {iteration} : échec de la récupération ({e})")
            listings = None

        if listings is not None:
            last_listings = listings
            if first_run:
                # Premier lancement : on mémorise sans spammer les logements déjà là
                seen_set = set(listings.keys())
                notify_start(len(listings))
                first_run = False
                print(f"[{stamp}] iter {iteration} : état initial "
                      f"({len(listings)} logement(s)) mémorisé, pas de notif de listing.")
            else:
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
