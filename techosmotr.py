#!/usr/bin/env python3
"""Техосмотр Hermes Agent простым русским языком.

Запускает hermes-system-doctor (только чтение) и превращает его JSON-отчёт
в короткую сводку для владельца агента: всё в порядке / что не так / что делать.

  python techosmotr.py                      # сводка в консоль
  python techosmotr.py --full               # подробно по всем проверкам
  python techosmotr.py --report report.json # разобрать готовый отчёт doctor
  python techosmotr.py --telegram           # отправить сводку в Telegram
                                            # (TECHOSMOTR_TG_TOKEN, TECHOSMOTR_TG_CHAT в окружении)
Код выхода: 0 — всё хорошо, 1 — есть предупреждения, 2 — есть проблемы.
"""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys, tempfile, urllib.parse, urllib.request
from pathlib import Path

COMPONENTS = {
    "discovery": "Поиск установки", "profiles": "Профили агентов", "config": "Настройки (config.yaml)",
    "gateway": "Шлюз сообщений (Telegram и др.)", "cron": "Расписания (cron)", "logs": "Журналы ошибок",
    "auth_surface": "Файлы доступа", "memory": "Память", "skills": "Навыки", "plugins": "Плагины",
    "mcp": "Подключённые MCP-серверы", "post_update_drift": "Изменения после обновления",
}
LEVEL = {"OK": ("✅", "в порядке"), "UNKNOWN": ("❔", "не удалось проверить"),
         "WARN": ("⚠️", "есть замечания"), "FAIL": ("❌", "есть проблема"),
         "NEEDS_APPROVAL": ("🛑", "нужно решение владельца")}
RU = {
    "home.missing": "Папка Hermes не найдена",
    "profiles.none_detected": "Не найдено ни одного профиля агента", "profiles.empty_home": "Папка Hermes пустая",
    "profiles.path_not_directory": "Путь профиля — не папка",
    "config.missing": "Нет файла настроек config.yaml", "config.parse_error": "Файл настроек повреждён (ошибка YAML)",
    "cron.metadata_parse_error": "Не читается описание расписаний", "cron.script_missing": "Расписание ссылается на несуществующий скрипт",
    "cron.script_outside_profile": "Скрипт расписания лежит вне папки агента", "cron.workdir_missing": "У расписания нет рабочей папки",
    "gateway.config_unreadable": "Не читаются настройки шлюза сообщений", "gateway.pid_stale_or_unreadable": "Шлюз сообщений, возможно, не запущен (устаревший PID)",
    "gateway.platform_shape_invalid": "Ошибка в настройках платформы (Telegram и др.)",
    "mcp.command_missing": "MCP-сервер: не найдена команда запуска", "mcp.env_ref_missing": "MCP-сервер ссылается на отсутствующую переменную окружения",
    "mcp.http_without_tls": "MCP-сервер подключён без шифрования (http)", "mcp.inline_secret_env": "В настройках MCP ключ записан открытым текстом",
    "mcp.inline_secret_header": "В заголовках MCP ключ записан открытым текстом", "mcp.url_invalid": "MCP-сервер: неверный адрес",
    "memory.file_large": "Файл памяти слишком большой — агент тратит лишние токены", "memory.profile_large": "Память профиля разрослась",
    "memory.dir_many_files": "В памяти слишком много файлов", "memory.json_invalid": "Файл памяти повреждён",
    "plugins.configured_missing": "Плагин указан в настройках, но не установлен", "plugins.inline_secret_metadata": "В описании плагина ключ открытым текстом",
    "plugins.manifest_missing": "У плагина нет описания (manifest)", "plugins.manifest_invalid": "Описание плагина повреждено", "plugins.too_many": "Слишком много плагинов",
    "post_update.cache_stale": "После обновления остался устаревший кэш", "post_update.git_head_unknown": "Не удалось определить версию Hermes",
    "post_update.local_origin_ref_differs": "Локальная версия отличается от официальной",
    "skills.duplicate_name": "Два навыка с одинаковым именем", "skills.frontmatter_missing": "У навыка нет заголовка (frontmatter)",
    "skills.frontmatter_invalid": "Заголовок навыка повреждён", "skills.name_missing": "У навыка нет имени",
    "skills.link_missing": "Навык ссылается на отсутствующий файл", "skills.too_many": "Слишком много навыков — агент тратит лишние токены",
}
ORDER = ["OK", "UNKNOWN", "WARN", "FAIL", "NEEDS_APPROVAL"]
CODE_EXT = (".py", ".pyc", ".js", ".mjs", ".ts", ".md", ".txt", ".json5")
CODE_DIRS = ("/tests/", "/test/", "site-packages/", "hermes-agent/", "/src/", "node_modules/")


def is_noise(f: dict) -> bool:
    """Служебные отметки, а не проблемы: пропущенные симлинки и «подозрительные»
    имена файлов, которые на деле являются исходным кодом самого Hermes."""
    fid = f.get("id", "")
    if fid.endswith(".symlink_skipped"):
        return True
    if f.get("component") == "auth_surface" and fid.startswith("auth_surface.") and fid not in (
            "auth_surface.env_file", "auth_surface.private_key_like", "auth_surface.no_profiles"):
        paths = [e for e in f.get("evidence", []) if "/" in e or "." in e]
        path = paths[-1] if paths else ""
        if path.endswith(CODE_EXT) or any(d in "/" + path for d in CODE_DIRS):
            return True
    return False


def run_doctor(home: str) -> dict:
    exe = shutil.which("hermes-system-doctor")
    if not exe:
        sys.exit("Не найден hermes-system-doctor. Установите: pip install git+https://github.com/AlekseiUL/hermes-system-doctor")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "report.json"
        subprocess.run([exe, "full", "--hermes-home", home, "--json", "--output", str(out)],
                       check=False, capture_output=True, text=True, timeout=600)
        if not out.exists():
            sys.exit("Диагностика не сформировала отчёт — проверьте путь к Hermes (--home).")
        return json.loads(out.read_text(encoding="utf-8"))


def summarize(rep: dict, full: bool = False) -> tuple[str, int]:
    raw = [f for c in rep.get("checks", []) for f in c.get("findings", [])
           if f.get("severity") != "OK"]
    findings = [f for f in raw if not is_noise(f)]
    noise = len(raw) - len(findings)
    status = max((f.get("severity", "UNKNOWN") for f in findings), key=ORDER.index, default="OK")
    if not raw:
        status = rep.get("status", "OK")
    icon, word = LEVEL.get(status, LEVEL["UNKNOWN"])
    findings.sort(key=lambda f: -ORDER.index(f.get("severity", "UNKNOWN")))
    lines = [f"{icon} Техосмотр агента: {word}.", f"Проверено разделов: {len(rep.get('checks', []))}, замечаний: {len(findings)}."]
    if noise:
        lines.append(f"Служебных отметок (не проблемы): {noise} — скрыты.")
    if findings:
        lines.append("")
        for f in findings[:8]:
            fi, _ = LEVEL.get(f.get("severity"), LEVEL["UNKNOWN"])
            comp = COMPONENTS.get(f.get("component"), f.get("component"))
            prof = f" (профиль «{f['profile']}»)" if f.get("profile") else ""
            lines.append(f"{fi} {comp}{prof}: {RU.get(f.get('id'), f.get('summary'))}")
            if f.get("next_action"):
                lines.append(f"   → что сделать: {f['next_action']}")
        if len(findings) > 8:
            lines.append(f"…и ещё {len(findings) - 8}. Подробно: --full")
        if any(f.get("requires_approval") for f in findings):
            lines.append("\n🛑 Есть действия, которые нельзя делать без решения владельца.")
    if full:
        lines.append("\nПо разделам:")
        for c in rep.get("checks", []):
            real = [f for f in c.get("findings", []) if f.get("severity") != "OK" and not is_noise(f)]
            sev = max((f.get("severity", "UNKNOWN") for f in real), key=ORDER.index, default="OK") if c.get("findings") else c.get("severity")
            ci, _ = LEVEL.get(sev, LEVEL["UNKNOWN"])
            lines.append(f"{ci} {COMPONENTS.get(c['name'], c['name'])} — {c.get('summary', '')}")
    lines.append("\nДиагностика только читает: ничего не изменено и не перезапущено.")
    code = 0 if status == "OK" else (1 if status in ("WARN", "UNKNOWN") else 2)
    return "\n".join(lines), code


def send_telegram(text: str) -> None:
    token, chat = os.environ.get("TECHOSMOTR_TG_TOKEN"), os.environ.get("TECHOSMOTR_TG_CHAT")
    if not token or not chat:
        sys.exit("Для --telegram задайте TECHOSMOTR_TG_TOKEN и TECHOSMOTR_TG_CHAT в окружении.")
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=30)


def main() -> None:
    ap = argparse.ArgumentParser(description="Техосмотр Hermes Agent на русском")
    ap.add_argument("--home", default=os.path.expanduser("~/.hermes"), help="папка Hermes (по умолчанию ~/.hermes)")
    ap.add_argument("--report", help="готовый JSON-отчёт hermes-system-doctor")
    ap.add_argument("--full", action="store_true", help="подробно по всем разделам")
    ap.add_argument("--telegram", action="store_true", help="отправить сводку в Telegram")
    a = ap.parse_args()
    rep = json.loads(Path(a.report).read_text(encoding="utf-8")) if a.report else run_doctor(a.home)
    text, code = summarize(rep, a.full)
    print(text)
    if a.telegram:
        send_telegram(text)
    sys.exit(code)


if __name__ == "__main__":
    main()
