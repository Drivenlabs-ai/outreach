#!/usr/bin/env bash
# Hook PostToolUse — quand un fichier campagne est édité (un prompt de message ou campaign.json),
# vérifie la conformance prompts ↔ variables de la séquence Lemlist. Best-effort, NON bloquant :
# c'est le harnais qui vérifie, pas Claude, donc aucune dérive ne passe inaperçue par oubli.
#
# Sens unique (Lemlist = vérité) : le hook ne fait que LIRE et signaler. Il n'écrit jamais.
set -uo pipefail

input="$(cat 2>/dev/null)" || exit 0
fp="$(printf '%s' "$input" | python3 -c 'import sys,json
try: d=json.load(sys.stdin)
except Exception: d={}
print((d.get("tool_input") or {}).get("file_path",""))' 2>/dev/null)"
[ -z "$fp" ] && exit 0

# Ne réagit qu'aux fichiers d'une verticale de Prospection.
case "$fp" in
  */Prospection/*/prompts/*.md)  cfg="$(dirname "$(dirname "$fp")")/campaign.json" ;;
  */Prospection/*/campaign.json) cfg="$fp" ;;
  *) exit 0 ;;
esac
[ -f "$cfg" ] || exit 0

out="$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/routine.py" verify --config "$cfg" 2>/dev/null)" || exit 0
aligned="$(printf '%s' "$out" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("aligned"))
except Exception: print("")' 2>/dev/null)"

if [ "$aligned" = "False" ]; then
  echo "⚠️ outreach — dérive prompts ↔ séquence détectée sur $cfg : $out"
fi
exit 0
