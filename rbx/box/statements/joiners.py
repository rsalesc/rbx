import dataclasses
import pathlib
from abc import ABC, abstractmethod
from typing import Any, Dict, List

import typer

from rbx import console
from rbx.box.statements.builders import (
    StatementBuilderContest,
    StatementCodeLanguage,
)
from rbx.box.statements.schema import Joiner, JoinerType, JoinTexToPDF, StatementType


@dataclasses.dataclass
class StatementJoinerContext:
    languages: List[StatementCodeLanguage]
    params: Joiner
    root: pathlib.Path

    def build_jinja_kwargs(self) -> Dict[str, Any]:
        return {'languages': self.languages}


class StatementJoiner(ABC):
    @abstractmethod
    def name(self) -> JoinerType:
        pass

    @abstractmethod
    def default_params(self) -> Joiner:
        pass

    @abstractmethod
    def input_type(self) -> StatementType:
        pass

    @abstractmethod
    def output_type(self) -> StatementType:
        pass

    @abstractmethod
    def joined_type(self) -> StatementType:
        pass

    @abstractmethod
    def build(
        self,
        input: bytes,
        context: StatementJoinerContext,
        contest: StatementBuilderContest,
        verbose: bool = False,
    ) -> bytes:
        pass


class TeX2PDFJoiner(StatementJoiner):
    def name(self) -> JoinerType:
        return JoinerType.TexToPDF

    def default_params(self) -> Joiner:
        return JoinTexToPDF(type=JoinerType.TexToPDF)

    def input_type(self) -> StatementType:
        return StatementType.TeX

    def output_type(self) -> StatementType:
        return StatementType.PDF

    def joined_type(self) -> StatementType:
        return StatementType.TeX

    def build(
        self,
        input: bytes,
        context: StatementJoinerContext,
        contest: StatementBuilderContest,
        verbose: bool = False,
    ) -> bytes:
        from rbx.box.statements.latex import (
            MAX_PDFLATEX_RUNS,
            Latex,
            decode_latex_output,
            should_rerun,
        )

        latex = Latex(input.decode())
        latex_result = latex.build_pdf(context.root)
        pdf = latex_result.pdf
        logs = decode_latex_output(latex_result.result.stdout)
        runs = 1

        while pdf is not None and should_rerun(logs) and runs < MAX_PDFLATEX_RUNS:
            console.console.print(
                'Re-running pdfLaTeX to get cross-references right...'
            )
            latex_result = latex.build_pdf(context.root)
            pdf = latex_result.pdf
            logs = decode_latex_output(latex_result.result.stdout)
            runs += 1

        if pdf is None:
            console.console.print(f'{logs}')
            console.console.print('[error]PdfLaTeX compilation failed.[/error]')
            raise typer.Exit(1)

        if verbose:
            console.console.print(f'{logs}')

        return pdf


JOINER_LIST: List[StatementJoiner] = [TeX2PDFJoiner()]
