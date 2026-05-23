import tree_sitter_cpp
from tree_sitter import Language, Parser


def test_cpp_parser_constructs_and_parses():
    language = Language(tree_sitter_cpp.language())
    parser = Parser(language)
    tree = parser.parse(b'int main() { return 0; }')
    assert tree.root_node.type == 'translation_unit'
    assert not tree.root_node.has_error
