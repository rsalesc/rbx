import pathlib
from typing import Optional

import pytest
from pydantic import BaseModel

from rbx.box.statements.expander import expand_statements
from rbx.box.statements.schema import Statement, StatementType


class MockStatement(BaseModel):
    """Mock statement class for testing purposes."""

    name: str
    extends: Optional[str] = None
    title: str = ''
    content: str = ''
    priority: int = 0


class TestExpandStatements:
    """Tests for the expand_statements function."""

    def test_expand_statements_no_extensions(self):
        """Test that statements without extensions are returned unchanged."""
        statements = [
            MockStatement(name='stmt1', title='Title 1', content='Content 1'),
            MockStatement(name='stmt2', title='Title 2', content='Content 2'),
        ]

        result = expand_statements(statements)

        assert len(result) == 2
        assert result[0].name == 'stmt1'
        assert result[0].title == 'Title 1'
        assert result[0].content == 'Content 1'
        assert result[1].name == 'stmt2'
        assert result[1].title == 'Title 2'
        assert result[1].content == 'Content 2'

    def test_expand_statements_single_extension(self):
        """Test expansion of a statement that extends another."""
        statements = [
            MockStatement(name='base', title='Base Title', content='Base Content'),
            MockStatement(name='derived', extends='base', title='Derived Title'),
        ]

        result = expand_statements(statements)

        assert len(result) == 2

        # Base statement should be unchanged
        base_result = next(stmt for stmt in result if stmt.name == 'base')
        assert base_result.title == 'Base Title'
        assert base_result.content == 'Base Content'

        # Derived statement should inherit from base and override title
        derived_result = next(stmt for stmt in result if stmt.name == 'derived')
        assert derived_result.title == 'Derived Title'
        assert derived_result.content == 'Base Content'  # Inherited
        assert derived_result.extends == 'base'  # Should preserve extends field

    def test_expand_statements_chain_extension(self):
        """Test expansion of a chain of extensions (A -> B -> C)."""
        statements = [
            MockStatement(
                name='root', title='Root', content='Root content', priority=1
            ),
            MockStatement(name='middle', extends='root', title='Middle', priority=2),
            MockStatement(name='leaf', extends='middle', content='Leaf content'),
        ]

        result = expand_statements(statements)

        assert len(result) == 3

        # Root should be unchanged
        root_result = next(stmt for stmt in result if stmt.name == 'root')
        assert root_result.title == 'Root'
        assert root_result.content == 'Root content'
        assert root_result.priority == 1

        # Middle should inherit from root
        middle_result = next(stmt for stmt in result if stmt.name == 'middle')
        assert middle_result.title == 'Middle'  # Overridden
        assert middle_result.content == 'Root content'  # Inherited
        assert middle_result.priority == 2  # Overridden

        # Leaf should inherit from expanded middle (which has inherited from root)
        leaf_result = next(stmt for stmt in result if stmt.name == 'leaf')
        assert leaf_result.title == 'Middle'  # Inherited from middle
        assert leaf_result.content == 'Leaf content'  # Overridden
        assert leaf_result.priority == 2  # Inherited from middle

    def test_expand_statements_multiple_children(self):
        """Test expansion when one statement is extended by multiple others."""
        statements = [
            MockStatement(name='parent', title='Parent', content='Shared content'),
            MockStatement(name='child1', extends='parent', title='Child 1'),
            MockStatement(
                name='child2', extends='parent', title='Child 2', priority=10
            ),
        ]

        result = expand_statements(statements)

        assert len(result) == 3

        # Parent should be unchanged
        parent_result = next(stmt for stmt in result if stmt.name == 'parent')
        assert parent_result.title == 'Parent'
        assert parent_result.content == 'Shared content'

        # Both children should inherit from parent
        child1_result = next(stmt for stmt in result if stmt.name == 'child1')
        assert child1_result.title == 'Child 1'
        assert child1_result.content == 'Shared content'
        assert child1_result.priority == 0  # Default value

        child2_result = next(stmt for stmt in result if stmt.name == 'child2')
        assert child2_result.title == 'Child 2'
        assert child2_result.content == 'Shared content'
        assert child2_result.priority == 10

    def test_expand_statements_complex_inheritance_tree(self):
        """Test expansion of a complex inheritance tree."""
        statements = [
            MockStatement(name='root1', title='Root 1', content='Root 1 content'),
            MockStatement(name='root2', title='Root 2', content='Root 2 content'),
            MockStatement(name='branch1', extends='root1', priority=5),
            MockStatement(name='branch2', extends='root2', priority=10),
            MockStatement(name='leaf1', extends='branch1', title='Leaf 1'),
            MockStatement(name='leaf2', extends='branch2', title='Leaf 2'),
        ]

        result = expand_statements(statements)

        assert len(result) == 6

        # Check leaf1 has correct inheritance chain
        leaf1_result = next(stmt for stmt in result if stmt.name == 'leaf1')
        assert leaf1_result.title == 'Leaf 1'  # Overridden
        assert (
            leaf1_result.content == 'Root 1 content'
        )  # Inherited from root1 via branch1
        assert leaf1_result.priority == 5  # Inherited from branch1

        # Check leaf2 has correct inheritance chain
        leaf2_result = next(stmt for stmt in result if stmt.name == 'leaf2')
        assert leaf2_result.title == 'Leaf 2'  # Overridden
        assert (
            leaf2_result.content == 'Root 2 content'
        )  # Inherited from root2 via branch2
        assert leaf2_result.priority == 10  # Inherited from branch2

    def test_expand_statements_preserves_order(self):
        """Test that the function preserves the original order of statements."""
        statements = [
            MockStatement(name='third', extends='first', title='Third'),
            MockStatement(name='first', title='First'),
            MockStatement(name='second', extends='first', title='Second'),
        ]

        result = expand_statements(statements)

        # Should preserve original order: third, first, second
        assert [stmt.name for stmt in result] == ['third', 'first', 'second']

    def test_expand_statements_cycle_detection(self):
        """Test that cycles in extensions are detected and raise an error."""
        statements = [
            MockStatement(name='stmt1', extends='stmt2'),
            MockStatement(name='stmt2', extends='stmt1'),
        ]

        with pytest.raises(ValueError, match='Failed to expand statements.*cycle'):
            expand_statements(statements)

    def test_expand_statements_self_reference_cycle(self):
        """Test that self-reference creates a cycle and is detected."""
        statements = [
            MockStatement(name='stmt1', extends='stmt1'),
        ]

        with pytest.raises(ValueError, match='Failed to expand statements.*cycle'):
            expand_statements(statements)

    def test_expand_statements_three_way_cycle(self):
        """Test detection of a three-way cycle."""
        statements = [
            MockStatement(name='stmt1', extends='stmt2'),
            MockStatement(name='stmt2', extends='stmt3'),
            MockStatement(name='stmt3', extends='stmt1'),
        ]

        with pytest.raises(ValueError, match='Failed to expand statements.*cycle'):
            expand_statements(statements)

    def test_expand_statements_missing_parent(self):
        """Test that extending a non-existent statement creates a cycle error."""
        statements = [
            MockStatement(name='child', extends='nonexistent'),
        ]

        with pytest.raises(ValueError, match='Failed to expand statements.*cycle'):
            expand_statements(statements)

    def test_expand_statements_empty_list(self):
        """Test that an empty list returns an empty list."""
        result = expand_statements([])
        assert result == []

    def test_expand_statements_single_statement(self):
        """Test expansion of a single statement without extensions."""
        statements = [MockStatement(name='single', title='Single Statement')]

        result = expand_statements(statements)

        assert len(result) == 1
        assert result[0].name == 'single'
        assert result[0].title == 'Single Statement'

    def test_expand_statements_complex_field_inheritance(self):
        """Test that complex field types are properly inherited and merged."""
        # Using more complex data that would test deepmerge behavior
        statements = [
            MockStatement(name='base', title='Base', content='base_content'),
            MockStatement(name='override', extends='base', title='Override'),
        ]

        result = expand_statements(statements)

        override_result = next(stmt for stmt in result if stmt.name == 'override')
        assert override_result.title == 'Override'  # Should be overridden
        assert override_result.content == 'base_content'  # Should be inherited
        assert override_result.name == 'override'  # Should preserve own name
        assert override_result.extends == 'base'  # Should preserve extends field

    def test_expand_statements_mixed_scenario(self):
        """Test a mixed scenario with both independent and dependent statements."""
        statements = [
            MockStatement(name='independent', title='Independent'),
            MockStatement(name='base', title='Base', content='Base content'),
            MockStatement(name='derived', extends='base', title='Derived'),
            MockStatement(name='another_independent', title='Another Independent'),
        ]

        result = expand_statements(statements)

        assert len(result) == 4

        # Independent statements should be unchanged
        independent = next(stmt for stmt in result if stmt.name == 'independent')
        assert independent.title == 'Independent'
        assert independent.content == ''

        another_independent = next(
            stmt for stmt in result if stmt.name == 'another_independent'
        )
        assert another_independent.title == 'Another Independent'

        # Derived should inherit from base
        derived = next(stmt for stmt in result if stmt.name == 'derived')
        assert derived.title == 'Derived'
        assert derived.content == 'Base content'


class TestExpandStatementsIntegration:
    """Integration tests using the real Statement class."""

    def test_expand_real_statements_basic_inheritance(self):
        """Test expansion with real Statement objects."""
        statements = [
            Statement(
                name='base-en',
                language='en',
                title='Base Problem',
                path=pathlib.Path('statement.tex'),
                assets=['common.sty', 'images/*.png'],
                vars={'MAX_N': 1000, 'TIME_LIMIT': '2 seconds'},
            ),
            Statement(
                name='derived-pt',
                extends='base-en',
                language='pt',
                title='Problema Base',
                path=pathlib.Path('statement-pt.tex'),
                vars={'TIME_LIMIT': '2 segundos'},  # Override one variable
            ),
        ]

        result = expand_statements(statements)

        assert len(result) == 2

        # Base statement should be unchanged
        base_result = next(stmt for stmt in result if stmt.name == 'base-en')
        assert base_result.title == 'Base Problem'
        assert base_result.language == 'en'
        assert base_result.assets == ['common.sty', 'images/*.png']
        assert base_result.vars == {'MAX_N': 1000, 'TIME_LIMIT': '2 seconds'}

        # Derived statement should inherit most fields but override some
        derived_result = next(stmt for stmt in result if stmt.name == 'derived-pt')
        assert derived_result.title == 'Problema Base'  # Overridden
        assert derived_result.language == 'pt'  # Overridden
        assert derived_result.path == pathlib.Path('statement-pt.tex')  # Overridden
        assert derived_result.assets == ['common.sty', 'images/*.png']  # Inherited
        assert derived_result.vars == {
            'MAX_N': 1000,
            'TIME_LIMIT': '2 segundos',
        }  # Merged
        assert derived_result.extends == 'base-en'  # Preserved

    def test_expand_real_statements_complex_inheritance(self):
        """Test complex inheritance with conversion steps and configurations."""
        statements = [
            Statement(
                name='base',
                title='Base Statement',
                language='en',
                path=pathlib.Path('base.tex'),
                type=StatementType.rbxTeX,
                assets=['base.sty'],
                vars={'N': 100, 'M': 200},
            ),
            Statement(
                name='child1',
                extends='base',
                title='Child 1',
                assets=['child1.png'],  # Additional assets
                vars={'N': 150},  # Override one variable
            ),
            Statement(
                name='grandchild',
                extends='child1',
                title='Grandchild',
                language='es',
                vars={'M': 300, 'K': 50},  # Override and add variables
            ),
        ]

        result = expand_statements(statements)

        assert len(result) == 3

        # Check grandchild has correct inheritance
        grandchild = next(stmt for stmt in result if stmt.name == 'grandchild')
        assert grandchild.title == 'Grandchild'  # Overridden
        assert grandchild.language == 'es'  # Overridden
        assert grandchild.path == pathlib.Path('base.tex')  # Inherited from base
        assert grandchild.type == StatementType.rbxTeX  # Inherited from base
        assert grandchild.assets == [
            'base.sty',
            'child1.png',
        ]  # Merged assets from base and child1
        assert grandchild.vars == {'N': 150, 'M': 300, 'K': 50}  # Complex merge

    def test_expand_real_statements_multilingual(self):
        """Test expansion of multilingual statements."""
        statements = [
            Statement(
                name='problem-en',
                title='Problem Title',
                language='en',
                path=pathlib.Path('problem-en.tex'),
                vars={'TITLE': 'Problem', 'AUTHOR': 'John Doe'},
            ),
            Statement(
                name='problem-pt',
                extends='problem-en',
                title='Título do Problema',
                language='pt',
                path=pathlib.Path('problem-pt.tex'),
                vars={'TITLE': 'Problema'},
            ),
            Statement(
                name='problem-es',
                extends='problem-en',
                title='Título del Problema',
                language='es',
                path=pathlib.Path('problem-es.tex'),
                vars={'TITLE': 'Problema', 'AUTHOR': 'Juan Pérez'},
            ),
        ]

        result = expand_statements(statements)

        assert len(result) == 3

        # Portuguese should inherit from English but override some fields
        pt_result = next(stmt for stmt in result if stmt.name == 'problem-pt')
        assert pt_result.vars == {'TITLE': 'Problema', 'AUTHOR': 'John Doe'}  # Merged
        assert pt_result.language == 'pt'

        # Spanish should also inherit from English but with different overrides
        es_result = next(stmt for stmt in result if stmt.name == 'problem-es')
        assert es_result.vars == {'TITLE': 'Problema', 'AUTHOR': 'Juan Pérez'}  # Merged
        assert es_result.language == 'es'

    def test_expand_real_statements_cycle_detection(self):
        """Test cycle detection with real Statement objects."""
        statements = [
            Statement(name='stmt1', extends='stmt2'),
            Statement(name='stmt2', extends='stmt1'),
        ]

        with pytest.raises(ValueError, match='Failed to expand statements.*cycle'):
            expand_statements(statements)

    def test_expand_real_statements_preserves_defaults(self):
        """Test that default values are preserved when not overridden."""
        statements = [
            Statement(
                name='base',
                title='Base',
                # Using mostly defaults
            ),
            Statement(
                name='derived',
                extends='base',
                title='Derived',
                language='pt',  # Override just one field
            ),
        ]

        result = expand_statements(statements)

        derived = next(stmt for stmt in result if stmt.name == 'derived')
        assert derived.title == 'Derived'  # Overridden
        assert derived.language == 'pt'  # Overridden
        assert derived.path == pathlib.Path()  # Inherited default
        assert derived.type == StatementType.rbxTeX  # Inherited default
        assert derived.assets == []  # Inherited default
        assert derived.vars == {}  # Inherited default
