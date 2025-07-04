import pathlib
from abc import ABC, abstractmethod
from typing import Type

from rbx import console


class BaseImporter(ABC):
    @classmethod
    @abstractmethod
    def name(cls) -> str:
        pass

    @abstractmethod
    async def import_package(self, pkg_path: pathlib.Path, into_path: pathlib.Path):
        pass


class BaseContestImporter(ABC):
    @classmethod
    @abstractmethod
    def name(cls) -> str:
        pass

    @abstractmethod
    async def import_package(self, pkg_path: pathlib.Path, into_path: pathlib.Path):
        pass


async def run_importer(
    importer_cls: Type[BaseImporter], pkg_path: pathlib.Path, into_path: pathlib.Path
):
    importer = importer_cls()
    console.console.print(
        f'Importing package from [item]{pkg_path}[/item] to [item]{into_path}[/item] with [item]{importer.name()}[/item]...'
    )
    await importer.import_package(pkg_path, into_path)
