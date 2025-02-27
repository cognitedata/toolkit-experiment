"""This is a small CLI used to develop Toolkit."""

import itertools
import re
from datetime import date
from pathlib import Path
from typing import Literal, get_args

import marko
import marko.block
import marko.element
import marko.inline
import typer
from packaging.version import Version, parse
from rich import print

from cognite_toolkit._version import __version__

REPO_ROOT = Path(__file__).parent
CHANGELOG = REPO_ROOT / "CHANGELOG.cdf-tk.md"
TEMPLATE_CHANGELOG = REPO_ROOT / "CHANGELOG.templates.md"
TBD_HEADING = "## TBD"
IMAGE_NAME = "cognite/toolkit"
CDF_TOML = REPO_ROOT / "cdf.toml"

VALID_CHANGELOG_HEADERS = {"Added", "Changed", "Removed", "Fixed"}
BUMP_OPTIONS = Literal["major", "minor", "patch", "skip"]
VALID_BUMP_OPTIONS = get_args(BUMP_OPTIONS)

app = typer.Typer(
    add_completion=False,
    help=__doc__,
    pretty_exceptions_short=False,
    pretty_exceptions_show_locals=False,
    pretty_exceptions_enable=False,
)


@app.command()
def bump(
    major: bool = False,
    minor: bool = False,
    patch: bool = False,
    alpha: bool = False,
    beta: bool = False,
    stable: bool = False,
    verbose: bool = False,
) -> None:
    version_files = [
        REPO_ROOT / "pyproject.toml",
        REPO_ROOT / "cognite_toolkit" / "_version.py",
        REPO_ROOT / "cdf.toml",
        *(REPO_ROOT / "tests" / "data").rglob("cdf.toml"),
        *(REPO_ROOT / "tests" / "data").rglob("_build_environment.yaml"),
        *(REPO_ROOT / "cognite_toolkit").rglob("cdf.toml"),
    ]
    docker_image_files = [
        *(REPO_ROOT / "cognite_toolkit" / "_repo_files").rglob("*.yml"),
        *(REPO_ROOT / "cognite_toolkit" / "_repo_files").rglob("*.yaml"),
    ]
    version = parse(__version__)

    if alpha and version.is_prerelease and version.pre[0] == "a":
        suffix = f"a{version.pre[1] + 1}"
    elif alpha and version.is_prerelease and version.pre[0] == "b":
        raise typer.BadParameter("Cannot bump to alpha version when current version is a beta prerelease.")
    elif alpha and not version.is_prerelease:
        suffix = "a1"
    elif beta and version.is_prerelease and version.pre[0] == "a":
        suffix = "b1"
    elif beta and version.is_prerelease and version.pre[0] == "b":
        suffix = f"b{version.pre[1] + 1}"
    elif beta and not version.is_prerelease:
        raise typer.BadParameter("Cannot bump to beta version when current version is not an alpha prerelease.")
    elif stable and not version.is_prerelease:
        raise typer.BadParameter("Cannot bump to stable version when current version is not a prerelease.")
    else:
        suffix = ""

    if major:
        new_version = Version(f"{version.major + 1}.0.0{suffix}")
    elif minor:
        new_version = Version(f"{version.major}.{version.minor + 1}.0{suffix}")
    elif patch:
        new_version = Version(f"{version.major}.{version.minor}.{version.micro + 1}{suffix}")
    elif alpha or beta or stable:
        new_version = Version(f"{version.major}.{version.minor}.{version.micro}{suffix}")
    else:
        raise typer.BadParameter("You must specify one of major, minor, patch, alpha, or beta.")

    # Update Changelog
    changelog = CHANGELOG.read_text()
    template_changelog = TEMPLATE_CHANGELOG.read_text()
    if TBD_HEADING not in changelog and TBD_HEADING not in template_changelog:
        print(
            f"  [bold red]ERROR [/][red]There are no changes to release[/][bold red]:[/]"
            f" The changelogs do not contain a TBD section: {TBD_HEADING}."
        )
        raise SystemExit(1)

    today = date.today().strftime("%Y-%m-%d")
    new_heading = f"## [{new_version}] - {today}"

    for content, file, name in [
        (changelog, CHANGELOG, "cdf CLI"),
        (template_changelog, TEMPLATE_CHANGELOG, "templates"),
    ]:
        if TBD_HEADING in content:
            content = content.replace(TBD_HEADING, new_heading)
            file.write_text(content)
            if verbose:
                typer.echo(f"Updated {file.name!r} changelog with new heading: {new_heading}.")
        else:
            new_changelog: list[str] = []
            has_added_entry = False
            for line in content.splitlines():
                if not has_added_entry and line.startswith("##"):
                    new_changelog.append(new_heading)
                    new_changelog.append("")
                    new_changelog.append(f"No changes to {name}.")
                    new_changelog.append("")
                    has_added_entry = True

                new_changelog.append(line)
            with file.open("w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(new_changelog) + "\n")

    for file in version_files:
        file.write_text(file.read_text().replace(str(version), str(new_version), 1))
        if verbose:
            typer.echo(f"Bumped version from {version} to {new_version} in {file}.")
    for file in docker_image_files:
        file.write_text(file.read_text().replace(f"{IMAGE_NAME}:{version!s}", f"{IMAGE_NAME}:{new_version!s}", 1))
        if verbose:
            typer.echo(f"Bumped version from {version} to {new_version} in {file}.")

    typer.echo(f"Bumped version from {version} to {new_version} in {len(version_files)} files.")


@app.command("alpha")
def set_alpha(off: bool = False) -> None:
    if not off:
        return
    is_feature_flag = False
    new_lines = []
    for line in CDF_TOML.read_text().splitlines():
        if header_match := re.match(r"\[(\w+)\]", line.strip()):
            header = header_match.group(1)
            print(header)
            if header == "alpha_flags":
                is_feature_flag = True
            else:
                is_feature_flag = False
        if is_feature_flag:
            line = line.replace("true", "false")
        new_lines.append(line)

    CDF_TOML.write_text("\n".join(new_lines) + "\n")


@app.command("changelog")
def create_changelog() -> None:
    last_git_message_file = REPO_ROOT / "last_git_message.txt"
    last_git_message = last_git_message_file.read_text()
    if "## Changelog" not in last_git_message:
        print("No changelog entry found in the last commit message.")
        raise SystemExit(1)
    changelog_text = last_git_message.split("## Changelog")[1].strip()
    changelog_items = [
        item for item in marko.parse(changelog_text).children if not isinstance(item, marko.block.BlankLine)
    ]
    if not changelog_items:
        print("No changelog items found in the last commit message.")
        raise SystemExit(1)
    first_item = changelog_items[0]
    if not isinstance(first_item, marko.block.List):
        print("The first item in the changelog must be a list with the type of change.")
        raise SystemExit(1)
    version_bump = _get_change(first_item)
    if version_bump == "skip":
        print("No changes to release.")
        return
    if not changelog_items[1:]:
        print(f"Trying to {version_bump} bump but no changes found in the changelog.")
        raise SystemExit(1)
    if not _is_header(changelog_items[1], level=2, text="cdf"):
        print("The first header in the changelog must be '## cdf'.")
        raise SystemExit(1)
    cdf_entries = list(itertools.takewhile(lambda x: not _is_header(x, level=2), changelog_items[2:]))
    _validate_entries(cdf_entries, "cdf")
    no = next((no for no, item in enumerate(changelog_items) if _is_header(item, level=2, text="templates")), None)
    if no is None:
        print("No '## templates' section found in the changelog.")
        raise SystemExit(1)
    if not changelog_items[no + 1 :]:
        print("No template entries found in the changelog.")
        raise SystemExit(1)
    template_entries = list(changelog_items[no + 1 :])
    _validate_entries(template_entries)


def _is_header(item: marko.element.Element, level: int, text: str | None = None):
    if not (
        isinstance(item, marko.block.Heading)
        and item.level == level
        and isinstance(item.children[0], marko.inline.RawText)
    ):
        return False
    return text is None or item.children[0].children == text


def _get_change(item: marko.block.List) -> Literal["major", "minor", "patch", "skip"]:
    selected: list[Literal["major", "minor", "patch", "skip"]] = []
    for child in item.children:
        if not isinstance(child, marko.block.ListItem):
            print(f"Unexpected item in changelog: {child}")
            raise SystemExit(1)
        if not isinstance(child.children[0], marko.block.Paragraph):
            print(f"Unexpected item in changelog: {child.children[0]}")
            raise SystemExit(1)
        if not isinstance(child.children[0].children[0], marko.inline.RawText):
            print(f"Unexpected item in changelog: {child.children[0].children[0]}")
            raise SystemExit(1)
        list_text = child.children[0].children[0].children
        if list_text.startswith("[ ]"):
            continue
        elif list_text.startswith("[x]"):
            change_type = list_text.removeprefix("[x]").strip()
            if change_type.casefold() not in VALID_BUMP_OPTIONS:
                print(f"Unexpected change type in changelog: {change_type}")
                raise SystemExit(1)
            selected.append(change_type.casefold())
        else:
            print(f"Unexpected item in changelog: {list_text}")
            raise SystemExit(1)

    if len(selected) > 1:
        print("You can only select one type of change.")
        raise SystemExit(1)
    if not selected:
        print("You must select a type of change.")
        raise SystemExit(1)
    return selected[0]


def _validate_entries(items: list[marko.element.Element], section: str) -> None:
    seen_headers: set[str] = set()
    if not items:
        print(f"No entries found in the {section} section of the changelog.")
        raise SystemExit(1)
    if (
        isinstance(items[0], marko.block.Paragraph)
        and isinstance(items[0].children[0], marko.inline.RawText)
        and items[0].children[0].children == "No changes."
    ):
        return

    raise NotImplementedError("This function is not implemented yet.")


# This is just for demo purposes, to test the secret plugin in the Toolkit CLI
import_app = typer.Typer(
    pretty_exceptions_short=False, pretty_exceptions_show_locals=False, pretty_exceptions_enable=False
)


@import_app.command("cdf")
def cdf(
    ctx: typer.Context,
) -> None:
    """Import resources into Cognite Data Fusion."""
    print("Ran CDF Import Command")


CDF_TK_PLUGIN = {
    "bump": app,
    "import": import_app,
}

if __name__ == "__main__":
    app()
