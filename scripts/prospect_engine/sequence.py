"""Édition de séquence — logique déterministe.

Gate d'éditabilité (on ne mute jamais une campagne qui tourne) + aplatissement lisible de la séquence
pour montrer l'état et connaître les ids à muter. L'I/O Lemlist vit dans lemlist.py ; le jugement
(intention NL → mutations, copy, prompts) vit en session. On n'écrit jamais la séquence depuis le run.
"""


class CampaignActive(Exception):
    """La campagne envoie (ou état inconnu) : muter sa séquence est interdit — la mettre en pause d'abord."""


def ensure_editable(campaign):
    """Garde dure avant toute mutation de séquence. Refuse `running` (envoi actif ; éditer pendant l'envoi
    a un effet non documenté sur les leads en cours) et l'état inconnu (on ne mute pas à l'aveugle). Les
    autres états (paused, draft, ended, archived, errors) ne sont pas en envoi actif → éditables."""
    status = (campaign or {}).get("status")
    if status == "running":
        raise CampaignActive("campagne active (running) — mets-la en pause avant d'éditer la séquence")
    if status is None:
        raise CampaignActive("état de campagne inconnu — édition refusée par sécurité")
    return status


def summarize(sequences_res):
    """Aplatit la réponse get_campaign_sequences (dict {sequence_id: {steps: [...]}}) en une liste plate
    d'étapes portant leur `sequence_id`, `step_id` et `index` — de quoi montrer la séquence et cibler les
    mutations. L'`index` est requis pour le réordonnancement et le recreate de canal (re-poser la position).
    `subject` vaut None pour les types d'étape sans sujet."""
    out = []
    seqs = sequences_res if isinstance(sequences_res, dict) else {}
    for seq_id, seq in seqs.items():
        if not isinstance(seq, dict):
            continue
        for st in seq.get("steps") or []:
            out.append({
                "sequence_id": seq_id,
                "step_id": st.get("_id"),
                "index": st.get("index"),
                "type": st.get("type"),
                "delay": st.get("delay"),
                "subject": st.get("subject"),
                "message": st.get("message"),
            })
    return out
