#!/usr/bin/env bash
# Synchronise les workflows du plugin vers leur emplacement officiel (~/.claude/workflows/).
#
# Pourquoi : « workflow » n'est pas un composant de plugin reconnu. Les .workflow.js doivent
# vivre dans ~/.claude/workflows/ pour que le runtime les traite comme workflows sauvegardés
# (et les expose en /commandes). Ce script, déclenché par le hook SessionStart, copie le repo
# (source de vérité) vers cet emplacement à chaque démarrage de session.
#
# Idempotent (copie seulement si le contenu diffère) → install au premier run, mise à jour
# après un git pull, auto-réparation si un fichier a été supprimé. Copie et non symlink : un
# plugin de marketplace voit sa racine changer à chaque update, un symlink finirait pendouillant.
set -euo pipefail

SRC="${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT non défini}/workflows"
DST="${HOME}/.claude/workflows"

[ -d "$SRC" ] || exit 0
mkdir -p "$DST"

shopt -s nullglob
for f in "$SRC"/*.workflow.js; do
  name="$(basename "$f")"
  if [ ! -f "$DST/$name" ] || ! cmp -s "$f" "$DST/$name"; then
    cp "$f" "$DST/$name"
    echo "outreach: workflow synchronisé → $name"
  fi
done
exit 0
