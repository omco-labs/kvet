#!/usr/bin/env bash
set -euo pipefail

REPO="omco-labs/kvet"
BRANCH="main"
BASE_URL="https://raw.githubusercontent.com/${REPO}/${BRANCH}/skills/kvet"
FILES=(
  "SKILL.md"
  "scripts/export_kiro_session.py"
)

echo ""
echo "  Kvet Skill Installer"
echo "  --------------------"
echo ""
echo "  [1] Project level  - install into the current repo (.kiro/)"
echo "  [2] User level     - install into your home directory (~/.kiro/)"
echo ""

printf "  Choose [1/2]: "
read -r choice </dev/tty

case "$choice" in
  1)
    dirs=(".kiro")
    label="project"
    ;;
  2)
    dirs=("$HOME/.kiro")
    label="user"
    ;;
  *)
    echo "  Invalid choice. Exiting."
    exit 1
    ;;
esac

echo ""

for dir in "${dirs[@]}"; do
  mkdir -p "$dir/skills/kvet/scripts"
  for file in "${FILES[@]}"; do
    printf "  Downloading %s -> %s/skills/kvet/%s\n" "$file" "$dir" "$file"
    curl -fsSL "${BASE_URL}/${file}" -o "$dir/skills/kvet/$file"
  done
done

echo ""
echo "  Done! Kvet skill installed at the ${label} level."

if [ "$label" = "project" ]; then
  echo ""
  echo "  Installed to:"
  for dir in "${dirs[@]}"; do
    echo "    $dir/skills/kvet/"
  done
  echo ""
  echo "  You may want to commit these files to your repo."
fi

echo ""
