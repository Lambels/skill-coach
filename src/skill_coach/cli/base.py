"""Command base class and shared types for the CLI."""

from __future__ import annotations

import argparse
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Literal, Optional


SectionKind = Literal["table", "panel"]

ColumnSpec = tuple[str, str, Optional[Callable], str, Optional[str]]


@dataclass
class Section:
    title: str
    data: dict | list[dict] | str
    kind: SectionKind = "table"
    columns: Optional[list[ColumnSpec]] = None


class Command(ABC):
    REGISTRY: dict[str, type["Command"]] = {}

    name: str = ""
    help: str = ""
    aliases: list[str] = []
    abstract: bool = False
    needs_sweep: bool = True

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.__dict__.get("abstract", False):
            return
        if not cls.name:
            raise TypeError(f"{cls.__name__} must declare a non-empty `name`")
        if cls.name in Command.REGISTRY:
            existing = Command.REGISTRY[cls.name].__qualname__
            raise RuntimeError(
                f"command name {cls.name!r} already registered by {existing}; "
                f"{cls.__qualname__} would shadow it"
            )
        Command.REGISTRY[cls.name] = cls

    @abstractmethod
    def register(self, parser: argparse.ArgumentParser) -> None: ...

    @abstractmethod
    def run(self, args, conn: sqlite3.Connection) -> list[Section]: ...


class WindowedCommand(Command):
    abstract = True

    def register(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--days", type=int, default=None,
            help="restrict to the last N days (default: all time)",
        )
