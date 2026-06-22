"""Sourcing People DB — code déterministe (le moteur), appelé par le routeur AVANT le workflow.

Lit UNE page du pool à la position du curseur (ordre People DB stable), exclut les URLs déjà en
campagne (filtre `out` natif), projette chaque résultat vers la forme lead, renvoie le curseur
suivant. Le `limitation` natif (quota/24 h) est remonté — on le respecte, on ne throttle pas.
"""
from prospect_engine import lemlist


EXCLUDE_CAP = 900  # sous le plafond du filtre `out` Lemlist (~1000)


def loaded_urls(contacts, campaign_id, cap=EXCLUDE_CAP):
    """linkedinUrl des contacts déjà membres de cette campagne (via `contact.campaigns`), borné au
    plafond `out`. C'est « Lemlist = mémoire » des leads déjà chargés."""
    urls = [c["linkedinUrl"] for c in contacts
            if c.get("linkedinUrl")
            and any(cm.get("campaignId") == campaign_id for cm in (c.get("campaigns") or []))]
    return set(urls[:cap])


def _project(r):
    """Résultat brut People DB → forme lead (linkedinUrl, fullName, jobTitle, companyName, …)."""
    return {
        "linkedinUrl": r.get("lead_linkedin_url") or "",
        "fullName": r.get("full_name") or "",
        "jobTitle": r.get("title") or r.get("title_normalized") or "",
        "companyName": r.get("current_exp_company_name") or r.get("company_name") or "",
        "location": r.get("location") or "",
        "summary": r.get("summary") or "",
        "headline": r.get("headline") or "",
        "people_db_id": str(r.get("lead_id") or ""),
    }


def source(key, filters, cursor, target, *, exclude=()):
    """Une page du pool People DB à la position `cursor` (ordre stable). Renvoie les candidats
    projetés (hors `exclude`), le curseur suivant, le quota restant, et `exhausted` si la page est
    courte (fin de pool). `exclude` (linkedinUrl déjà en campagne) part en filtre `out` natif ET
    re-filtré côté client (filet si la troncature au plafond laisse passer)."""
    exclude = set(exclude)
    search = list(filters)
    if exclude:
        search = search + [{"filterId": "leadLinkedInUrl", "in": [], "out": list(exclude)}]
    st, res = lemlist.search_people(key, search, cursor, target)
    if st != 200 or not isinstance(res, dict):
        return {"candidats": [], "limitation": None, "next_cursor": cursor + 1, "exhausted": True}
    results = res.get("results") or []
    candidats, have = [], set()
    for r in results:
        lead = _project(r)
        url = lead["linkedinUrl"]
        if not url or url in exclude or url in have:
            continue
        candidats.append(lead)
        have.add(url)
    return {"candidats": candidats[:target], "limitation": res.get("limitation"),
            "next_cursor": cursor + 1, "exhausted": len(results) < target}
