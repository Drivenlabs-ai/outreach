---
name: new-campaign
description: Crée une nouvelle campagne de prospection outbound pour une verticale dans le plugin prospect-routine. Déclencher quand l'utilisateur veut monter, créer ou lancer une campagne pour un segment ("crée une campagne pour les agences immo", "nouvelle verticale X", "monte une prospection pour Y", "setup outbound pour Z", "on attaque le marché des cabinets dentaires"), ou démarrer une campagne Lemlist multicanale de zéro. Ne pas déclencher pour faire tourner (sourcing quotidien) ou modifier une campagne existante.
---

# new-campaign (W1) — créer une campagne pour une verticale

## Vue d'ensemble

Crée une verticale de prospection de bout en bout : **valide l'ICP et l'angle avec l'utilisateur
(interactif), puis matérialise la campagne en autonomie** (fichiers d'intelligence → validation du
prompt `icpFit` → campagne Lemlist → smoke test → prêt).

**Principe** : toi (Claude de session) tu **orchestres des briques déjà construites et testées** — tu
n'écris pas de code. Le moteur (`scripts/routine.py`) fait l'I/O Lemlist et l'état ; les workflows
`icp-check` et `sourcing` portent le jugement IA ; `/lemlist` porte la craft (ICP, séquence, copy). Ton
rôle : la conversation d'alignement, la rédaction des fichiers d'intelligence, et l'enchaînement des
commandes.

**Frontière dure** : la phase 1 est **interactive** (l'ICP/angle exige le jugement de l'utilisateur) ;
la phase 2 est **autonome** mais s'arrête à deux gardes — avant toute **mutation Lemlist** et avant le
**flip `dry_run`**.

## Quand l'utiliser

- L'utilisateur veut **créer / monter / lancer** une campagne pour une nouvelle verticale ou un segment.
- Pas pour : faire tourner le sourcing quotidien d'une campagne existante (→ run/W3), ni pour modifier
  une campagne déjà créée (→ edits ciblés).

## Le flux

<!-- Phase 1 — Task 2 -->
## Phase 1 — Alignement ICP + angle (interactif)

## Phase 2 — Matérialisation (autonome, gardée)

### 1. Écrire les fichiers d'intelligence

### 2. icp-check — aligner le prompt icpFit

### 3. W2 — créer la campagne Lemlist

### 4. Smoke test — 1 lead en review

### 5. Passer en prêt (flip dry_run)

## Robustesse & reprise

## Référence

Détail du scaffold de verticale (arbre des fichiers, forme de `campaign.json`, id du template de flux
par défaut, contrat de variables) : `references/new-campaign/vertical-scaffold.md`.
