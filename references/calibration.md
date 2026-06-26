# Calibration du rendement de sourcing (référence partagée new-campaign / edit-campaign)

Chargée avant de définir ou de modifier le ciblage d'une campagne. Le rendement = la densité de décideurs ICP que les filtres People DB ramènent. Calibrer = ajuster les filtres pour que l'échantillon sourcé contienne surtout des décideurs qualifiables, avant le run. Geste obligatoire et autonome : un ciblage n'est pas « prêt » tant qu'il n'est pas calé.

## Le funnel à deux étages

Deux filtres en série, à ne jamais confondre :

- **Filtres People DB** (`campaign.json` → `filters`) — le filet de pioche, grossier : qui ENTRE dans le funnel.
- **Prompt icpFit** (`prompts/icpFit.md`) — le tri fin, par l'IA : qui PASSE parmi les sourcés.

Le rendement se cale sur le premier ; la précision se règle sur le second. Les deux se mesurent ensemble via icp-check.

## La boucle (en coulisses)

1. **Échantillonner sans consommer** : `source --config <campaign.json> --sample --target <N>` (N ≈ 20). `--sample` n'avance pas le curseur — on mesure sans brûler le pool. Renvoie l'échantillon + `total` (taille du vivier). `total` proche de 0 ou `exhausted` → filtre trop étroit ou invalide : élargir, ne pas committer.
2. **Scorer** : workflow `icp-check`, `args = { prompt_icpFit: <contenu de prompts/icpFit.md>, sample: <candidats>, model: "haiku" }` → `{ verdicts: [{ lead, qualifie, raison }] }`.
3. **Mesurer** : rendement = qualifiés / taille de l'échantillon.
4. **Ajuster si bas** par les bons leviers (ci-dessous), puis ré-échantillonner. Boucle bornée et jugée : vise un échantillon nettement majoritaire en décideurs, pas la perfection ; pas de seuil automatique.

## Les leviers

- **Filtres : séniorité + taille d'entreprise.** Restreindre aux tiers de direction (`seniority` : Ownership / Firm Leadership, Executive Leadership, Department Leadership, People Management / Leadership) et aux petites structures (`currentCompanyHeadcount`) monte la densité de décideurs. C'est le levier principal du rendement.
- **Jamais filtrer sur le titre.** Un fondateur de petite structure se présente souvent en « agent » ou « conseiller » ; un filtre de titre l'exclurait — or c'est le cœur de cible. Le titre se juge à l'étape IA (icpFit sait promouvoir un fondateur via son résumé), pas au sourcing.
- **Prompt icpFit** : si l'échantillon est plein de décideurs mais d'une activité voisine hors-cible (gestion, syndic, promotion, conciergerie…), c'est le tri fin qu'on resserre, pas les filtres.

## Ce qui remonte à l'utilisateur

Le user est non-technique ; le skill est un pont, pas un cockpit. La calibration tourne en coulisses. Ne fais émerger QUE :

- un **arbitrage métier** que l'ICP ne tranche pas — portée ↔ précision (serré = surtout des décideurs, audience plus petite ; large = plus de volume, plus de tri) ;
- une **alerte** si l'audience est trop petite pour démarrer.

Sinon, tranche seul d'après l'ICP validé. Clos par un **récap en clair** : qui la campagne va toucher + le récap lisible des filtres retenus, en rappelant que c'est le filet large et que **le vrai tri est fait par l'IA ensuite**.

Banni dans le dialogue user : « rendement % », « séniorité », « filterId », « icp-check », « échantillon », « calibration ». Ces mots vivent dans cette référence, pas devant lui.
