#!/usr/bin/env bash
# Установка техосмотра для Hermes Agent (Linux/WSL). Только чтение, ничего не меняет в Hermes.
set -euo pipefail
DIR="$HOME/techosmotr"
mkdir -p "$DIR"
python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q "git+https://github.com/AlekseiUL/hermes-system-doctor"
cp techosmotr.py "$DIR/"
mkdir -p "$HOME/.hermes/skills/techosmotr"
cp skill/techosmotr/SKILL.md "$HOME/.hermes/skills/techosmotr/"
sed -i "s#python3 ~/techosmotr/techosmotr.py#PATH=$DIR/.venv/bin:\$PATH python3 $DIR/techosmotr.py#" "$HOME/.hermes/skills/techosmotr/SKILL.md"
echo "Готово. Проверка: PATH=$DIR/.venv/bin:\$PATH python3 $DIR/techosmotr.py"
echo "Еженедельно в Telegram (пример для crontab -e):"
echo "  0 6 * * 0 TECHOSMOTR_TG_TOKEN=... TECHOSMOTR_TG_CHAT=... PATH=$DIR/.venv/bin:\$PATH python3 $DIR/techosmotr.py --telegram"
