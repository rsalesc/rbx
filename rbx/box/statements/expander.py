import collections
from typing import Any, List, TypeVar

from rbx.box.exception import RbxException
from rbx.box.fields import merge_pydantic_models

TypeVarT = TypeVar('TypeVarT', bound=Any)


class StatementExpanderError(RbxException):
    pass


def expand_statements(statements: List[TypeVarT]) -> List[TypeVarT]:
    seen_statements = set()
    for statement in statements:
        seen_statements.add(statement.name)

    deg = collections.defaultdict(int)
    dependencies = collections.defaultdict(list)
    for statement in statements:
        if statement.extends is not None:
            if statement.extends not in seen_statements:
                with StatementExpanderError() as err:
                    err.print(
                        f'[error]Failed to expand statements: statement [item]{statement.name}[/item] extends [item]{statement.extends}[/item], but [item]{statement.extends}[/item] is not defined.[/error]'
                    )
            deg[statement.name] += 1
            dependencies[statement.extends].append(statement.name)

    # Topological sort.
    #   - We need to expand statements in the order of dependencies.
    #   - This is a simple topological sort.
    #   - If there are multiple statements with indegree 0, we choose the first one.
    st_per_name = {}
    expanded = {}
    st = []
    for statement in statements:
        st_per_name[statement.name] = statement
        if deg[statement.name] == 0:
            st.append(statement)

    while st:
        statement = st.pop()
        expanded_statement = statement.model_copy()
        if statement.extends is not None:
            expanded_statement = merge_pydantic_models(
                expanded[statement.extends], statement
            )

        expanded[statement.name] = expanded_statement

        for dep_name in dependencies[statement.name]:
            deg[dep_name] -= 1
            if deg[dep_name] == 0:
                st.append(st_per_name[dep_name])

    if len(expanded) != len(statements):
        with StatementExpanderError() as err:
            err.print(
                f'[error]Failed to expand statements: only [item]{len(expanded)}[/item] out of [item]{len(statements)}[/item] were expanded. This means there is a cycle introduced by the `extends` field.[/error]'
            )

    return [expanded[statement.name] for statement in statements]
