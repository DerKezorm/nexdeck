"""Builds the kit of the workshop repository (KARTEN-13).

    python tools/workshop_kit.py --out ../workshop-out            # kit/ and schema/, with the drawing page built
    python tools/workshop_kit.py --out ../workshop-out --no-page  # without building the page (no Node needed)

``<out>/kit`` is what the actions of the workshop repository run, with no source of nexdeck beside it:

* ``nexdeck_kit/``: the modules that read and check a card, an own connection or a skin, the way nexdeck does when a
  person saves one, copied word for word from ``app/``. A few stand-ins take the place of what has nothing to do with checking
  (the database, the settings, the registry of connections, which keeps only the names of the kinds).
* ``check.py``: reads one file and says what is wrong with it, how far it reaches (``read``, ``buttons`` or ``login``)
  and what its demo data make of it (the ``WidgetData`` the renderers draw); for a skin, the style sheet nexdeck
  compiles from it, which the page wears for the pictures.
* ``page/``: the page that draws a ``WidgetData`` with the renderers of nexdeck, or a skin on the stage of the skin
  editor, light and dark (``frontend/workshop-preview.html``).
* ``VERSION``: the version of nexdeck and the commit the kit comes from.
* ``requirements.txt``: the plain Python packages the kit needs, at the versions of nexdeck.

``<out>/schema`` holds the JSON schemas of a card and of an own connection.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
FRONTEND = BACKEND.parent / "frontend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

PACKAGE = "nexdeck_kit"

#: Copied word for word, relative to ``app/``.
COPIED = (
    "credential_names.py",
    "cards/schema.py",
    "cards/buttons.py",
    "cards/blocks.py",
    "cards/formula.py",
    "cards/credentials.py",
    "cards/load.py",
    "cards/pipeline.py",
    "cards/integration.py",
    "cards/integration_schema.py",
    "cards/source.py",
    "cards/images.py",
    "adapters/base.py",
    "adapters/rawread.py",
    "adapters/custom.py",
    "services/themes.py",
    "skins/parts.json",
    "skins/css.py",
    "skins/schema.py",
    "skins/sprites.py",
    "skins/compile.py",
)

#: The packages of ``requirements.txt`` the copied modules import.
NEEDED_PACKAGES = ("pydantic", "pyyaml", "httpx", "jmespath", "tinycss2")

STAND_INS = {
    "__init__.py": '"""The checking kit of the nexdeck workshop."""\n\n__version__ = "{version}"\n',
    "cards/__init__.py": "from . import schema  # noqa: F401\n",
    # The registry keeps the names of the kinds nexdeck had when the kit was made, nothing else.
    "adapters/__init__.py": '''"""Stands in for the registry of connections: the kinds and categories of that nexdeck, and no adapters."""

from types import SimpleNamespace

_KINDS = frozenset({kinds})
_CATEGORIES = frozenset({categories})


def builtin_kinds():
    return _KINDS


def builtin_categories():
    return _CATEGORIES


def get_adapter(kind):
    if kind not in _KINDS:
        raise KeyError(kind)
    return SimpleNamespace(kind=kind, raw_read_commands=None)


def all_adapters():
    return []
''',
    "cards/store.py": '"""No saved cards in the kit."""\n\n\ndef get(db, slug):\n    return None\n',
    "db.py": '"""No database in the kit."""\n\nfrom contextlib import contextmanager\n\n\n@contextmanager\ndef db_session():\n    yield None\n',
    "services/__init__.py": '"""Only what the skins of the kit ask for."""\n',
    # The limits a skin file is held to, as that nexdeck had them; nothing that reads or writes the look of an installation.
    "services/appearance.py": '"""The limits of the look of nexdeck a skin file is held to, as the nexdeck of the kit had them."""\n\n'
    "CARD_STYLES = {card_styles}\nFONTS = {fonts}\nRADIUS = {radius}\nGAP = {gap}\n",
    "skins/__init__.py": '"""Skins, read and compiled as nexdeck does."""\n',
    "config.py": '"""The only setting a copied module asks for."""\n\nfrom types import SimpleNamespace\n\n\ndef get_settings():\n    return SimpleNamespace(resolved_secret_key=lambda: "nexdeck-workshop-kit")\n',
}

CHECK_PY = '''"""Checks one file of the workshop the way nexdeck does when a person saves it.

    python check.py FILE [--type card|integration|skin] [--scan LABEL=FILE ...]

``--scan`` reads a plain text of the submission (its description, its list of changes) and reports a key or a token in it.

Prints one JSON object on standard output. ``ok`` is false when anything is wrong; ``problems`` then lists every
reason, each with the place in the file. The exit code is 0 when ``ok``, 1 when not.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nexdeck_kit import __version__  # noqa: E402
from nexdeck_kit.adapters.custom import present  # noqa: E402
from nexdeck_kit.adapters.base import AdapterError  # noqa: E402
from nexdeck_kit.adapters.rawread import refuse_a_command  # noqa: E402
from nexdeck_kit.cards import credentials, integration, load, pipeline, schema  # noqa: E402
from nexdeck_kit.cards import integration_schema as isch  # noqa: E402

from nexdeck_kit.skins import compile as skin_compile  # noqa: E402
from nexdeck_kit.skins import css as skin_css  # noqa: E402
from nexdeck_kit.skins import schema as skin_schema  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from types import SimpleNamespace  # noqa: E402

#: The longest skin file nexdeck takes, and the names of the skins it ships, which no other skin may take.
SKIN_MAX = __SKIN_MAX__
SHIPPED_SKINS = __SHIPPED_SKINS__

_CARD = re.compile(r"^nexdeck-card[ \\t]*:", re.MULTILINE)
_INTEGRATION = re.compile(r"^nexdeck[ \\t]*:[ \\t]*[\\"']?integration[\\"']?[ \\t]*(#.*)?$", re.MULTILINE)


def plain(text):
    """A text of the author as one string, English first."""
    if isinstance(text, dict):
        return str(text.get("en") or next(iter(text.values()), ""))
    return "" if text is None else str(text)


def problem(code, message, path="", line=None):
    return {"code": code, "message": message, "path": path, "line": line}


def is_skin(text):
    try:
        data = json.loads(text)
    except ValueError:
        return False
    return isinstance(data, dict) and data.get("nexdeck_skin") == 1


def kind_of(text):
    if is_skin(text):
        return "skin"
    if _CARD.search(text):
        return "card"
    if _INTEGRATION.search(text):
        return "integration"
    return None


def inspect(text, wanted=None):
    out = {"ok": False, "kit": __version__, "type": None, "problems": []}
    found = kind_of(text)
    names = {"card": "a card", "integration": "a connection", "skin": "a skin"}
    if found == "skin":
        if wanted and wanted != found:
            out["problems"].append(problem("type_mismatch", f"The submission says it is {names[wanted]}, the text is a skin."))
            return out
        out["type"] = found
        _skin(text, out)
        out["ok"] = not out["problems"]
        return out
    if len(text) > schema.MAX_DEFINITION:
        out["problems"].append(problem("too_long", f"The definition is {len(text)} characters long, the limit is {schema.MAX_DEFINITION}."))
        return out
    if re.search(r"^---[ \\t\\r]*$", text, re.MULTILINE):
        out["problems"].append(problem("one_document", "A submission is one card or one connection, as a single YAML document."))
        return out
    if found is None:
        out["problems"].append(problem("unknown_type", "The text is neither a card (nexdeck-card: 1), a connection (nexdeck: integration) nor a skin (\\"nexdeck_skin\\": 1)."))
        return out
    if wanted and wanted != found:
        out["problems"].append(problem("type_mismatch", f"The submission says it is {names[wanted]}, the text is {names[found]}."))
        return out
    out["type"] = found
    try:
        if found == "card":
            _card(text, out)
        else:
            _integration(text, out)
    except load.CardInvalid as failure:
        out["problems"] += [problem(p.code, p.message, p.path, p.line) for p in failure.problems]
    out["ok"] = not out["problems"]
    return out


def _card(text, out):
    loaded = load.load_definition(text, running_version=__version__)
    definition = loaded.definition
    extra = [problem(p.code, p.message, p.path, p.line) for p in load.check_for_submission(definition)]
    for index, request in enumerate(definition.requests):
        try:
            refuse_a_command(SimpleNamespace(raw_read_commands=None), request.path)
        except AdapterError as failure:
            extra.append(problem("command_refused", failure.message, f"requests[{index}].path", loaded.lines.get(("requests", index, "path"))))
    out.update(
        slug=definition.slug,
        name=definition.name,
        description=definition.description or "",
        version=definition.version,
        min_nexdeck=definition.min_nexdeck or __version__,
        form=definition.form,
        size=[definition.size.w, definition.size.h] if definition.size else None,
        min_size=[definition.min_size.w, definition.min_size.h] if definition.min_size else None,
        requires=list(definition.requires),
        reads=[{"kind": definition.requires[0], "path": request.path} for request in definition.requests],
        buttons=[{"label": plain(one.label), "method": one.method, "path": one.path} for one in definition.buttons],
    )
    out["class"] = "buttons" if definition.buttons else "read"
    if extra:
        out["problems"] += extra
        return
    try:
        answers = pipeline.demo_answers(definition)
        result = pipeline.run(definition, answers or {}, budget_ms=1000)
        out["widget_data"] = present(definition, result, pictures=False).model_dump(mode="json")
    except AdapterError as failure:
        out["problems"].append(problem("demo_failed", f"The demo data do not work with this card: {failure.message}", "demo"))
    except Exception as failure:  # noqa: BLE001 - a demo that breaks the pipeline is a reason, not a crash
        out["problems"].append(problem("demo_failed", f"The demo data do not work with this card: {type(failure).__name__}.", "demo"))


def _skin(text, out):
    """A skin is read and compiled as nexdeck does when it is saved; what is compiled is what the pictures wear."""
    if len(text) > SKIN_MAX:
        out["problems"].append(problem("too_long", f"The skin is {len(text)} characters long, the limit is {SKIN_MAX}."))
        return
    try:
        skin = skin_schema.SkinFile.model_validate(json.loads(text))
    except ValidationError as failure:
        out["problems"] += [problem("bad_skin", error["msg"], ".".join(str(step) for step in error["loc"])) for error in failure.errors()]
        return
    out.update(
        slug=skin.key, name=skin.name, description=skin.description, version=skin.version, min_nexdeck=__version__,
        requires=[], reads=[], buttons=[],
    )
    # A skin reads nothing and presses nothing: it reaches no further than any other.
    out["class"] = "read"
    if skin.key in SHIPPED_SKINS:
        out["problems"].append(problem("taken", f"{skin.key} is the name of a skin nexdeck ships; give yours another.", "key"))
        return
    try:
        out["compiled"] = skin_compile.compile_skin(skin).as_json()
    except skin_css.SkinCssError as failure:
        out["problems"] += [problem("bad_css", one.message, "css", one.line) for one in failure.problems]


def _integration(text, out):
    loaded = integration.load_integration(text)
    definition = loaded.definition
    out.update(
        slug=definition.short,
        name=definition.name,
        description=definition.description,
        version="",
        min_nexdeck=__version__,
        requires=[],
        reads=[{"kind": "custom:" + definition.short, "path": one.path} for one in definition.reads],
        buttons=[],
        read_labels=[one.label for one in definition.reads],
        category_hint=definition.category,
    )
    out["class"] = "login" if definition.auth.type == "session" else "read"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--type", choices=("card", "integration", "skin"))
    parser.add_argument("--scan", action="append", default=[], metavar="LABEL=FILE")
    arguments = parser.parse_args()
    text = Path(arguments.file).read_text(encoding="utf-8")
    result = inspect(text, arguments.type)
    for item in arguments.scan:
        label, _, name = item.partition("=")
        found = credentials._value(Path(name).read_text(encoding="utf-8"), structure=False)
        if found:
            result["problems"].append(problem("secret_in_text", f"The {label} looks like it holds {credentials.PHRASES[found]}. Take it out.", label))
            result["ok"] = False
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def git_commit() -> str:
    """The commit the sources are at, with ``+changed`` when ``app/`` or the page differ from it."""
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=BACKEND, capture_output=True, text=True, check=True).stdout.strip()
        changed = subprocess.run(
            ["git", "status", "--porcelain", "--", "app", "../frontend/src", "../frontend/workshop-preview.html"],
            cwd=BACKEND, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return head + ("+changed" if changed else "")


def pinned(name: str) -> str:
    for line in (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines():
        found = re.match(rf"^{re.escape(name)}(\[.*\])?==([\w.]+)", line, re.IGNORECASE)
        if found:
            return f"{name}=={found.group(2)}"
    raise SystemExit(f"{name} is not pinned in requirements.txt")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def build_page(target: Path) -> None:
    """The page that draws a card or a skin, built by Vite from ``frontend/workshop-preview.html``.

    ⚠️ The page is looked for, not only the exit code: on Windows ``npx`` ran through the shell answered 0 for a build
    that failed (a package missing from ``node_modules``), and a kit without its page was written as if it were whole.
    """
    command = ["npx", "vite", "build", "-c", "vite.workshop.config.ts", "--outDir", str(target.resolve()), "--emptyOutDir"]
    done = subprocess.run(command, cwd=FRONTEND, shell=sys.platform == "win32", capture_output=True, text=True)
    if done.returncode != 0 or not (target / "workshop-preview.html").is_file():
        raise SystemExit("The drawing page did not build:\n" + done.stdout[-2000:] + done.stderr[-2000:])


def build(out: Path, *, page: bool = True, page_dir: Path | None = None) -> None:
    from app import __version__, adapters
    from app.cards import integration_schema, schema
    from app.services import appearance
    from app.skins import schema as skin_schema
    from app.skins import store as skin_store

    kit = out / "kit"
    if kit.exists():
        shutil.rmtree(kit)
    package = kit / PACKAGE
    for name in COPIED:
        text = (BACKEND / "app" / name).read_text(encoding="utf-8")
        write(package / name, text)
    stand_ins = dict(STAND_INS)
    stand_ins["__init__.py"] = stand_ins["__init__.py"].format(version=__version__)
    stand_ins["adapters/__init__.py"] = stand_ins["adapters/__init__.py"].format(
        kinds=repr(sorted(adapters.builtin_kinds())), categories=repr(sorted(adapters.builtin_categories()))
    )
    stand_ins["services/appearance.py"] = stand_ins["services/appearance.py"].format(
        card_styles=repr(appearance.CARD_STYLES), fonts=repr(appearance.FONTS), radius=repr(appearance.RADIUS), gap=repr(appearance.GAP)
    )
    for name, text in stand_ins.items():
        write(package / name, text)
    check = CHECK_PY.replace("__SKIN_MAX__", repr(skin_store.MAX_FILE)).replace("__SHIPPED_SKINS__", repr(sorted(skin_store.builtin())))
    write(kit / "check.py", check)
    write(kit / "VERSION", json.dumps({"nexdeck": __version__, "commit": git_commit()}, indent=2) + "\n")
    write(kit / "requirements.txt", "\n".join(pinned(name) for name in NEEDED_PACKAGES) + "\n")
    schemas = out / "schema"
    write(schemas / "card.schema.json", json.dumps(schema.json_schema(), indent=2, ensure_ascii=False) + "\n")
    write(schemas / "integration.schema.json", json.dumps(integration_schema.json_schema(), indent=2, ensure_ascii=False) + "\n")
    write(schemas / "skin.schema.json", json.dumps(skin_schema.SkinFile.model_json_schema(), indent=2, ensure_ascii=False) + "\n")
    if page_dir is not None:
        shutil.copytree(page_dir, kit / "page")
    elif page:
        build_page(kit / "page")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, type=Path, help="The directory that gets kit/ and schema/.")
    parser.add_argument("--no-page", action="store_true", help="Leave the drawing page out.")
    parser.add_argument("--page-dir", type=Path, help="Take over a page that is built already.")
    arguments = parser.parse_args()
    build(arguments.out, page=not arguments.no_page, page_dir=arguments.page_dir)
    print(f"kit written to {arguments.out / 'kit'}")


if __name__ == "__main__":
    main()
