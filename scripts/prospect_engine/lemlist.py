"""Client HTTP Lemlist — seul module à faire du réseau.

Centralise les pièges terrain : User-Agent obligatoire (403 WAF sinon), auth Basic à login vide,
et le SEUL throttle dont le moteur est responsable — le rate limit API 20 req/2s : sur 429 on
honore `Retry-After` puis backoff exponentiel borné. La cadence d'ENVOI, elle, est native Lemlist.
"""
import base64
import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

API = "https://api.lemlist.com/api"


def api_call(method, route, key, body=None, *, max_retries=2):
    """Appel API Lemlist → (status, parsed). parsed = JSON si le corps en est, sinon texte tronqué.

    Sur 429 : attend `Retry-After` (ou backoff exponentiel), retry jusqu'à `max_retries`.
    Erreur HTTP non-429 → (code, corps). Réseau/timeout → (0, message)."""
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(max_retries + 1):
        req = urllib.request.Request(API + route, data=data, method=method, headers={
            "Authorization": "Basic " + base64.b64encode(f":{key}".encode()).decode(),
            "Content-Type": "application/json",
            "User-Agent": "curl/8.7.1"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw.lstrip().startswith(("{", "[")) else raw[:300])
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries:
                ra = e.headers.get("Retry-After") if getattr(e, "headers", None) else None
                try:
                    wait = float(ra) if ra else 2.0
                except (TypeError, ValueError):
                    wait = 2.0
                time.sleep(max(wait, 2 ** attempt))
                continue
            return e.code, e.read().decode()[:300]
        except (urllib.error.URLError, TimeoutError) as e:
            return 0, str(e)[:300]


def paginate(key, route, params):
    """Toutes les pages d'un endpoint paginé (offset/limit), ou une liste brute."""
    out, offset, limit = [], 0, params.get("limit", 100)
    while True:
        st, res = api_call("GET", route + "?" + urlencode(dict(params, offset=offset)), key)
        if st != 200:
            break
        page = res if isinstance(res, list) else (res.get("data", []) if isinstance(res, dict) else [])
        out += page
        if len(page) < limit:
            break
        offset += limit
        time.sleep(0.15)
    return out


# ---------- wrappers d'endpoints (modèle C) ----------

def get_team(key):
    return api_call("GET", "/team", key)


def upsert_contact(key, payload):
    return api_call("POST", "/contacts", key, payload)


def add_to_list(key, list_id, contact_id):
    return api_call("POST", f"/contacts/lists/{list_id}/entities", key, {"contactIds": [contact_id]})


def create_lead(key, campaign_id, payload):
    """Crée un lead en campagne. `deduplicate=true` TOUJOURS : exclusion cross-campagne native
    par email (cf. spec 01 §0). Le lead naît en `review` ; create direct, marche campagne en pause."""
    return api_call("POST", f"/campaigns/{campaign_id}/leads?deduplicate=true", key, payload)


def update_variable(key, lead_id, name, value):
    """PATCH la VALEUR d'une variable existante du lead (défaut comme `icebreaker`, ou custom déjà
    définie). `POST /variables` ne sait que créer et refuse un nom existant ; c'est PATCH qui pose
    la valeur (cf. doc API `add-lead-variables`)."""
    return api_call("PATCH", f"/leads/{lead_id}/variables", key, {name: value})


def create_variable(key, lead_id, name, value):
    """POST crée une variable custom encore sans définition (échoue si le nom existe déjà)."""
    return api_call("POST", f"/leads/{lead_id}/variables", key, {name: value})


def launch_lead(key, lead_id):
    """Lance un lead en review dans la séquence d'envoi (Lemlist étale ensuite selon ses limites)."""
    return api_call("POST", f"/leads/review/{lead_id}", key)


def get_campaign(key, campaign_id):
    return api_call("GET", f"/campaigns/{campaign_id}", key)


def get_campaign_leads(key, campaign_id):
    return paginate(key, f"/campaigns/{campaign_id}/leads/", {"limit": 100})


def get_contacts(key):
    """Tous les contacts du compte (paginé). Chaque contact porte `linkedinUrl` + `campaigns[]`.
    Renvoie [] si l'appel échoue (le sourcing dégrade alors sans filtre d'exclusion)."""
    return paginate(key, "/contacts", {"limit": 100})


# ---------- setup (spec 02) ----------

def duplicate_campaign(key, template_id, name):
    """Duplique une campagne template (séquence + délais + variables copiés ; draft, 0 lead)."""
    return api_call("POST", f"/campaigns/{template_id}/duplicate", key, {"name": name})


def create_list(key, name):
    """Crée une liste de contacts statique (audience non synchronisée). Renvoie clt_…."""
    return api_call("POST", "/contacts/lists", key, {"name": name})


def get_campaign_sequences(key, campaign_id):
    """Séquences + steps d'une campagne — chaque step porte `type`, `delay`, `message` ({{variables}})."""
    return api_call("GET", f"/campaigns/{campaign_id}/sequences", key)


def get_lead(key, lead_id):
    """Lit un lead par id (renvoie ses `variables`) — fonctionne sans email, pour la garde launch."""
    return api_call("GET", f"/leads?id={lead_id}", key)


def search_people(key, filters, page=1, size=100):
    """Recherche dans la People DB. Réponse : results[] + total + `limitation` (quota restant/24 h)."""
    return api_call("POST", "/database/people", key, {"filters": filters, "page": page, "size": size})
