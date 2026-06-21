"""Livraison modèle C — « charger puis lancer ».

`load_lead` : chaîne composite (upsert → add-to-list → create-lead → set-variables), le lead finit
en `review`. Idempotente et reprenable via le ledger de reçus ; `deduplicate=true` toujours.
`launch_leads` : étape de lancement, séparée et gardée (`--confirm`), jamais automatique.

Seul `lemlist` fait du réseau ; ce module orchestre et journalise les reçus.
"""
from prospect_engine import lemlist, receipts

_MALFORMED_MARKERS = ("```", "**", "copie littérale", "message pour l'envoi")
_SKIP_STAGES = {"varset", "launched", "dup"}


# ---------- fonctions pures ----------

def is_clean_message(text):
    """Filet final avant livraison : ni vide, ni tiret cadratin, ni markdown/formule recopiée,
    ni séparateur, ni doublon manifeste (> 150 mots). Miroir du filtre côté moteur de rédaction."""
    if not text or not text.strip():
        return False
    if "—" in text or "–" in text:
        return False
    low = text.lower()
    if any(m in low for m in _MALFORMED_MARKERS):
        return False
    if any(line.strip() == "---" for line in text.splitlines()):
        return False
    if len(text.split()) > 150:
        return False
    return True


def contact_payload(lead):
    """Payload d'upsert `POST /contacts`. `companyName` EXCLU (l'upsert CRM le rejette en 400) —
    la société voyage avec le lead campagne, pas avec le contact."""
    p = {"linkedinUrl": lead.get("linkedinUrl") or ""}
    parts = (lead.get("fullName") or "").split()
    p["firstName"] = lead.get("firstName") or (parts[0] if parts else "")
    if len(parts) > 1:
        p["lastName"] = " ".join(parts[1:])
    for k in ("jobTitle", "location", "tagline", "industry", "summary", "email", "phone"):
        if lead.get(k):
            p[k] = lead[k]
    return p


def lead_payload(lead):
    """Payload de `create-lead` : identité + société (acceptée côté lead, contrairement au contact)."""
    p = contact_payload(lead)
    for k in ("companyName", "companyDomain"):
        if lead.get(k):
            p[k] = lead[k]
    return p


def build_load_plan(lead, variables, campaign_id, list_id):
    """Plan d'actions du chargement (dry-run) — ce que load_lead ferait, sans rien appeler."""
    return {"DRY_RUN": True, "campaign_id": campaign_id, "lead_key": receipts.lead_key(lead),
            "steps": [
                {"step": "upsert-contact", "payload": contact_payload(lead)},
                {"step": "add-to-list", "list_id": list_id},
                {"step": "create-lead", "payload": lead_payload(lead), "deduplicate": True},
                {"step": "set-variables", "variables": variables}]}


def _ok(status):
    return 200 <= status < 300


def _is_not_found(res):
    """Réponse Lemlist 'Variables X not found' → la variable n'a pas encore de définition (à créer).
    Toute AUTRE erreur ne doit PAS déclencher de création (un POST de repli créerait un doublon suffixé)."""
    s = res.get("status") if isinstance(res, dict) else res
    return "not found" in str(s or "").lower()


def _entity_id(res):
    """_id d'une réponse Lemlist, que l'entité soit à plat ou nichée sous `data`
    (POST /contacts et create-lead renvoient `{success, data: {_id}}`)."""
    if not isinstance(res, dict):
        return None
    if res.get("_id"):
        return res["_id"]
    data = res.get("data")
    return data.get("_id") if isinstance(data, dict) else None


# ---------- orchestration ----------

def load_lead(key, lead, variables, campaign_id, list_id, state_dir, *, confirm, dry_run):
    """Charge un lead en review (étapes 1→4). Idempotent + reprise à mi-chaîne via les reçus."""
    lk = receipts.lead_key(lead)
    if lk is None:
        return {"skipped": True, "reason": "no_identifier"}
    if not all(is_clean_message(v) for v in variables.values()):
        return {"skipped": True, "reason": "broken_message"}
    if dry_run or not confirm:
        return {"dry_run": True, "plan": build_load_plan(lead, variables, campaign_id, list_id)}

    rec = receipts.lookup(state_dir, campaign_id, lk)
    if rec and rec.get("stage") in _SKIP_STAGES:
        return {"skipped": True, "reason": "already_loaded", "lead_id": rec.get("lead_id")}

    stage = rec.get("stage") if rec else None
    contact_id = rec.get("contact_id") if rec else None
    lead_id = rec.get("lead_id") if rec else None

    def receipt(stg, ok=True, **extra):
        receipts.append_receipt(state_dir, dict(
            {"campaign_id": campaign_id, "lead_key": lk, "contact_id": contact_id,
             "lead_id": lead_id, "stage": stg, "ok": ok}, **extra))

    # 1. upsert contact (identité)
    if stage not in ("upserted", "listed", "created"):
        st, res = lemlist.upsert_contact(key, contact_payload(lead))
        contact_id = _entity_id(res)
        if not _ok(st) or not contact_id:
            return {"ok": False, "stage_reached": stage, "error": {"stage": "upsert", "status": st, "detail": str(res)[:120]}}
        receipt("upserted")

    # 2. add to list (audience non synchronisée) — best-effort, ne bloque pas la livraison
    if stage not in ("listed", "created"):
        lemlist.add_to_list(key, list_id, contact_id)
        receipt("listed")

    # 3. create lead in campaign (deduplicate=true natif)
    if stage != "created":
        st, res = lemlist.create_lead(key, campaign_id, lead_payload(lead))
        lead_id = _entity_id(res)
        if _ok(st) and not lead_id:
            receipt("dup", ok=False)  # email déjà dans une autre campagne → non inséré (natif)
            return {"skipped": True, "reason": "cross_campaign_email"}
        if not _ok(st) or not lead_id:
            return {"ok": False, "stage_reached": "listed", "error": {"stage": "create", "status": st, "detail": str(res)[:120]}}
        receipt("created")

    # 4. set variables (messages free-form) — PATCH pose la valeur d'une variable existante
    #    (défaut comme `icebreaker`, ou custom déjà définie) ; POST en repli pour créer une
    #    variable custom encore sans définition. POST seul échoue sur tout nom existant.
    for name, value in variables.items():
        st, res = lemlist.update_variable(key, lead_id, name, value)
        if not _ok(st) and _is_not_found(res):
            st, res = lemlist.create_variable(key, lead_id, name, value)
        if not _ok(st):
            return {"ok": False, "stage_reached": "created", "lead_id": lead_id,
                    "error": {"stage": "variables", "name": name, "status": st, "detail": str(res)[:120]}}
    receipt("varset")
    return {"ok": True, "skipped": False, "lead_id": lead_id, "contact_id": contact_id, "stage_reached": "varset"}


def launch_leads(key, items, campaign_id, state_dir, required_keys, *, confirm):
    """Lance des leads en review dans la séquence. Jamais automatique : `confirm` obligatoire.

    Garde dure (exigence non négociable) : avant de lancer, RELIT les variables réelles du lead dans
    Lemlist (par id, sans email) et REFUSE tout lead dont une clé requise (dérivée de la séquence) est
    vide ou absente. `items` = [{lead_id, lead_key}]. Lemlist étale ensuite l'envoi (Sending limits)."""
    if not confirm:
        return {"launched": [], "skipped": [], "errors": [], "refused": True}
    launched, skipped, errors = [], [], []
    for it in items:
        st, lead = lemlist.get_lead(key, it["lead_id"])
        if isinstance(lead, list):
            lead = lead[0] if lead else {}
        # Lemlist pose les variables en clés top-level du lead (pas sous une sous-clé `variables`).
        vars_src = lead if isinstance(lead, dict) else {}
        missing = [k for k in required_keys if not str(vars_src.get(k) or "").strip()]
        if missing:
            skipped.append({"lead_id": it["lead_id"], "reason": "variables_incompletes", "missing": missing})
            continue
        st2, res = lemlist.launch_lead(key, it["lead_id"])
        if _ok(st2):
            launched.append(it["lead_id"])
            receipts.append_receipt(state_dir, {
                "campaign_id": campaign_id, "lead_key": it.get("lead_key"),
                "contact_id": it.get("contact_id"), "lead_id": it["lead_id"], "stage": "launched", "ok": True})
        else:
            errors.append({"lead_id": it["lead_id"], "status": st2, "detail": str(res)[:120]})
    return {"launched": launched, "skipped": skipped, "errors": errors}
