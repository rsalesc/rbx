import collections
from typing import Any, List, TypeVar

from rbx.box.fields import merge_pydantic_models

TypeVarT = TypeVar('TypeVarT', bound=Any)


def expand_statements(statements: List[TypeVarT]) -> List[TypeVarT]:
    deg = collections.defaultdict(int)
    dependencies = collections.defaultdict(list)
    for statement in statements:
        if statement.extends is not None:
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
        raise ValueError(
            f'Failed to expand statements: only {len(expanded)} out of {len(statements)} were expanded. This means there is a cycle introduced by the `extends` field.'
        )

    return [expanded[statement.name] for statement in statements]
