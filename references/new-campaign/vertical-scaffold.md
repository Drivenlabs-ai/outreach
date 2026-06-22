# Scaffold d'une verticale (référence W1)

Chargé à la demande par le skill `new-campaign`. Détaille ce que la phase 2 écrit et avec quelles formes.

## Arbre du dossier verticale (Drive)

```
Prospection/<Vertical>/
├── icp.md · persona.md · pain-points.md · value-proposition.md · triggers.md   # intelligence métier
├── prompts/
│   ├── icpFit.md                 # prompt de qualification (testé par icp-check)
│   └── <step>.md                 # 1 prompt par message de la séquence (icebreaker / followup / closing…)
└── campaign.json                 # linkage + config (forme ci-dessous)
# Pas de eval-dataset/holdout : icp-check teste l'icpFit sur un échantillon live au setup (spec 04).
```

L'état machine vit ailleurs (`~/.claude/prospect-routine/<slug>/` : state / status / receipts / log) — jamais dans le Drive.

**Chemins (à passer en `--registry` / `--config`)** :
- registre : `<racine Prospection>/campaigns-registry.json` (Drive, sibling des dossiers verticale) — cf. architecture §2.
- `state_dir` : `~/.claude/prospect-routine/<slug>/` · clé API : `~/.claude/linkedin-prospect.local.md`.

## Forme de `campaign.json` (draft écrit en §1, ids remplis en §3)

```jsonc
{
  "campaign_id": null,                 // TU le remplis en §3 (sortie de duplicate-campaign) avant register
  "slug": "<slug>",
  "list_id": null,                     // TU le remplis en §3 (sortie de create-list) avant register
  "state_dir": "~/.claude/prospect-routine/<slug>",
  "api_key_file": "~/.claude/linkedin-prospect.local.md",
  "filters": [ /* filtres People DB issus de la phase 1 : { "filterId": …, "in": […], "out": […] } */ ],
  "models": { "scoring": "haiku", "writing": "sonnet", "judge": "sonnet" },
  "dry_run": true,                     // reste true jusqu'au flip final, gardé (§5)
  "sourcing_size": 50,                 // taille du lot People DB par run (curseur de page)
  "enrich": { "enabled": false },      // optionnel ; { enabled, directive, store, model } si activé
  "template_version": "1.0",
  "icp_global_version": "1"            // version de icp-global.md héritée (si présent)
}
```

## `register-campaign` — les deux payloads à assembler

`register-campaign` ne *calcule* rien : il **recopie `--data-file` dans `--campaign-json`** et **upsert
`--entry-file` dans le registre**. C'est donc à toi d'assembler les deux fichiers d'abord :

- `--data-file` = le **contenu final de `campaign.json`** (le draft ci-dessus + `campaign_id` / `list_id`
  relevés en §3). `--campaign-json` = le chemin de destination (le `campaign.json` de la verticale).
- `--entry-file` = l'**entrée registre** :

```jsonc
{ "slug": "<slug>", "campaign_id": "cam_…", "folder": "<Vertical>",
  "channels": ["linkedin", "email"], "status": "active",
  "config_path": "<chemin absolu vers le campaign.json de la verticale>" }
```

## `DEFAULT_FLOW_TEMPLATE_ID` — le template de flux par défaut

C'est la campagne Lemlist **maintenue à la main** qui porte la séquence multicanale de référence (visite
profil → invitation sans note → icebreaker → followup → closing ; les 3 messages référencent
`{{icebreaker}}` / `{{followup}}` / `{{closing}}`) — cf. spec 02 §0 (campagne `agence-immo`).

**Provenance** : c'est le `campaign_id` de la campagne `agence-immo` (spec 02 §0). Il est **fourni au
setup** — l'utilisateur le donne, ou il est inscrit dans une config plugin/`.local.md` ; **ne pas
l'inventer**. (Une résolution automatique via une entrée « template » du registre n'est **pas câblée** :
`config.resolve_campaign` ne matche aujourd'hui que `slug` / `campaign_id` — évolution future.) **Si l'id
n'est pas dans le contexte de session, demande-le explicitement à l'utilisateur** avant la 1re mutation.
En §3, `duplicate-campaign --template-id <cet id>` le duplique : séquence + variables IA voyagent, CRM
exclu, la nouvelle campagne naît en draft, compteurs à zéro.

## Contrat de variables (cœur de robustesse)

Trois bouts portent les **mêmes clés** :
- la séquence Lemlist référence `{{clé}}` dans ses messages,
- le prompt local s'appelle `prompts/<clé>.md`,
- le moteur pose une variable de lead `<clé>` au load.

**Source unique des clés = la séquence Lemlist** (lue par `fetch` / `verify`). Le local s'y conforme ;
on n'écrit jamais vers la séquence depuis le local. `verify` confronte les prompts présents aux variables
réelles : une variable de message **sans prompt** est **bloquante** (`missing_prompts`) ; un prompt **sans
variable** est un simple avertissement (`orphan_prompts`).
