import pytest
import typer

from rbx.box.code import maybe_rename_java_class
from rbx.box.environment import FileMapping


class TestMaybeRenameJavaClass:
    def test_basic_class_renaming(self, testing_pkg):
        """Test basic class renaming from Solution to Main"""
        java_file = testing_pkg.add_file('Solution.java')
        java_file.write_text("""public class Solution {
    public static void main(String[] args) {
        System.out.println("Hello World");
    }
}""")

        file_mapping = FileMapping(compilable='Main.java', executable='Main')
        result_path = maybe_rename_java_class(java_file, file_mapping)

        expected_content = """public class Main {
    public static void main(String[] args) {
        System.out.println("Hello World");
    }
}"""

        assert result_path.read_text() == expected_content
        assert result_path != java_file  # Should create new file

    def test_no_change_needed(self, testing_pkg):
        """Test when class is already named correctly"""
        java_file = testing_pkg.add_file('Main.java')
        original_content = """public class Main {
    public static void main(String[] args) {
        System.out.println("Hello World");
    }
}"""
        java_file.write_text(original_content)

        file_mapping = FileMapping(compilable='Main.java', executable='Main')
        result_path = maybe_rename_java_class(java_file, file_mapping)

        assert result_path.read_text() == original_content
        assert result_path == java_file  # Should return original file

    def test_whitespace_variations(self, testing_pkg):
        """Test handling of various whitespace patterns"""
        java_file = testing_pkg.add_file('MyClass.java')
        java_file.write_text("""public   class    MyClass   {
    public static void main(String[] args) {
        System.out.println("Hello World");
    }
}""")

        file_mapping = FileMapping(compilable='Main.java', executable='Main')
        result_path = maybe_rename_java_class(java_file, file_mapping)

        expected_content = """public class Main   {
    public static void main(String[] args) {
        System.out.println("Hello World");
    }
}"""

        assert result_path.read_text() == expected_content

    def test_complex_class_name(self, testing_pkg):
        """Test renaming with complex class names containing underscores, numbers, and dollar signs"""
        java_file = testing_pkg.add_file('Complex_Class_123$.java')
        java_file.write_text("""public class Complex_Class_123$ {
    public static void main(String[] args) {
        System.out.println("Hello World");
    }
}""")

        file_mapping = FileMapping(compilable='Main.java', executable='Main')
        result_path = maybe_rename_java_class(java_file, file_mapping)

        expected_content = """public class Main {
    public static void main(String[] args) {
        System.out.println("Hello World");
    }
}"""

        assert result_path.read_text() == expected_content

    def test_no_public_class_raises_error(self, testing_pkg):
        """Test that missing public class raises typer.Exit"""
        java_file = testing_pkg.add_file('NoPublic.java')
        java_file.write_text("""class NoPublic {
    public static void main(String[] args) {
        System.out.println("Hello World");
    }
}""")

        file_mapping = FileMapping(compilable='Main.java', executable='Main')

        with pytest.raises(typer.Exit):
            maybe_rename_java_class(java_file, file_mapping)

    def test_multiple_classes_only_renames_public(self, testing_pkg):
        """Test that only the public class gets renamed when multiple classes exist"""
        java_file = testing_pkg.add_file('MultiClass.java')
        java_file.write_text("""class Helper {
    public void help() {
        System.out.println("Helping");
    }
}

public class MultiClass {
    public static void main(String[] args) {
        Helper h = new Helper();
        h.help();
    }
}

class AnotherHelper {
    public void assist() {
        System.out.println("Assisting");
    }
}""")

        file_mapping = FileMapping(compilable='Main.java', executable='Main')
        result_path = maybe_rename_java_class(java_file, file_mapping)

        expected_content = """class Helper {
    public void help() {
        System.out.println("Helping");
    }
}

public class Main {
    public static void main(String[] args) {
        Helper h = new Helper();
        h.help();
    }
}

class AnotherHelper {
    public void assist() {
        System.out.println("Assisting");
    }
}"""

        assert result_path.read_text() == expected_content

    def test_preserves_comments_and_imports(self, testing_pkg):
        """Test that comments and imports are preserved during renaming"""
        java_file = testing_pkg.add_file('Solution.java')
        java_file.write_text("""// This is a comment
import java.util.*;
import java.io.*;

/* Multi-line comment
   about the solution */
public class Solution {
    // Another comment
    public static void main(String[] args) {
        System.out.println("Hello World"); // Inline comment
    }
}""")

        file_mapping = FileMapping(compilable='Main.java', executable='Main')
        result_path = maybe_rename_java_class(java_file, file_mapping)

        expected_content = """// This is a comment
import java.util.*;
import java.io.*;

/* Multi-line comment
   about the solution */
public class Main {
    // Another comment
    public static void main(String[] args) {
        System.out.println("Hello World"); // Inline comment
    }
}"""

        assert result_path.read_text() == expected_content

    def test_non_java_files_unaffected(self, testing_pkg):
        """Test that non-Java files are returned unchanged"""
        cpp_file = testing_pkg.add_file('solution.cpp')
        original_content = """#include <iostream>
using namespace std;

int main() {
    cout << "Hello World" << endl;
    return 0;
}"""
        cpp_file.write_text(original_content)

        file_mapping = FileMapping(compilable='solution.cpp', executable='solution')
        result_path = maybe_rename_java_class(cpp_file, file_mapping)

        assert result_path.read_text() == original_content
        assert result_path == cpp_file  # Should return original file unchanged
