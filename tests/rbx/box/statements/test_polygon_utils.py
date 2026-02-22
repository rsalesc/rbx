import pytest

from rbx.box.exception import RbxException
from rbx.box.statements.polygon_utils import PolygonTeXConfig, validate_polygon_tex


def test_valid_simple_text():
    latex = r'Hello \textbf{World} \textit{Italic}.'
    errors = validate_polygon_tex(latex)
    assert len(errors) == 0


def test_valid_math_blocks():
    # Content inside $...$ and $$...$$ should be ignored, so \invalid inside them is fine
    latex = r'Math: $ a + b + \invalidcommand $ and $$ \sum_{i=1}^n \invalid $$'
    errors = validate_polygon_tex(latex)
    assert len(errors) == 0


def test_invalid_command():
    latex = r'Some text \usepackage{geometry}'
    errors = validate_polygon_tex(latex)
    assert len(errors) == 1
    assert errors[0].construct == r'\usepackage'
    assert 'Unsupported command' in errors[0].reason


def test_invalid_math_delimiters():
    latex = r'Bad math \( a+b \) or \[ c+d \]'
    errors = validate_polygon_tex(latex)
    # Expect 2 errors: \( and \[
    # Note: \) and \] might also be flagged or just part of the skipped/parsed structure?
    # Usually \( is the start node.
    assert len(errors) >= 2
    constructs = [e.construct for e in errors]
    assert r'\(' in constructs
    assert r'\[' in constructs


def test_invalid_math_environment():
    latex = r'\begin{equation} E=mc^2 \end{equation}'
    errors = validate_polygon_tex(latex)
    assert len(errors) == 1
    assert errors[0].construct == r'\begin{equation}'


def test_valid_environments():
    latex = r"""
    \begin{itemize}
        \item Item 1
        \item Item 2
    \end{itemize}
    \begin{center}
        Centered text
    \end{center}
    """
    errors = validate_polygon_tex(latex)
    assert len(errors) == 0


def test_nested_invalid_command():
    latex = r'\begin{itemize} \item \section{Bad Section} \end{itemize}'
    errors = validate_polygon_tex(latex)
    assert len(errors) == 1
    assert errors[0].construct == r'\section'


def test_position_tracking():
    latex = 'Line 1\nLine 2\n\\invalid'
    errors = validate_polygon_tex(latex)
    assert len(errors) == 1
    # Line 3, somewhere at start
    line, col = errors[0].location
    assert line == 3


def test_url_image_cmds():
    latex = r'\url{http://google.com} \includegraphics{test.png}'
    errors = validate_polygon_tex(latex)
    assert len(errors) == 0


def test_custom_config():
    latex = r'\forbidden'
    config = PolygonTeXConfig.default()
    # Temporarily allow forbidden
    config.allowed_commands.add('forbidden')

    errors = validate_polygon_tex(latex, config=config)
    assert len(errors) == 0

    # Check default again
    errors_default = validate_polygon_tex(latex)
    assert len(errors_default) == 1


def test_recursion_on_invalid_command():
    # If \newcommand is invalid, we should still traverse its children (like \foo)
    latex = r'\newcommand{\foo}{bar}'
    errors = validate_polygon_tex(latex)
    assert len(errors) == 2
    constructs = {e.construct for e in errors}
    assert r'\newcommand' in constructs
    # TexSoup parses \foo as a command inside the first argument
    assert r'\foo' in constructs


def test_parsing_error():
    # Unclosed environment causes TexSoup to raise an error
    latex = r'\begin{itemize} \item Unclosed'
    with pytest.raises(RbxException) as excinfo:
        validate_polygon_tex(latex)
    assert 'Failed to parse LaTeX' in str(excinfo.value)


def test_convert_to_polygon_tex_basic():
    from rbx.box.statements.polygon_utils import convert_to_polygon_tex

    # 1. Math Conversion
    assert convert_to_polygon_tex(r'Inline \( x \)') == r'Inline $ x $'
    assert convert_to_polygon_tex(r'Display \[ y \]') == r'Display $$ y $$'

    # 2. Font Switch
    # Simple wrap
    assert convert_to_polygon_tex(r'\it Italic') == r'{\it Italic}'
    # Barrier stop
    assert (
        convert_to_polygon_tex(r'\it Italic \item Next') == r'{\it Italic }\item Next'
    )

    # 3. Environment Preservation
    latex_env = r'\begin{center} Text \end{center}'
    assert convert_to_polygon_tex(latex_env) == latex_env

    # 4. Command Deduplication Check
    # Ensure \section{Body} doesn't become \section{Body}Body
    assert convert_to_polygon_tex(r'\section{Title}') == r'\section{Title}'


def test_convert_preserves_dollar_sign_math():
    """$...$ and $$...$$ math blocks must be preserved as-is."""
    from rbx.box.statements.polygon_utils import convert_to_polygon_tex

    # Inline math with commands inside
    assert convert_to_polygon_tex(r'$1 \le N \le 150$') == r'$1 \le N \le 150$'

    # Multiple inline math blocks
    assert (
        convert_to_polygon_tex(r'integer $N$ ($1 \le N \le 150$)')
        == r'integer $N$ ($1 \le N \le 150$)'
    )

    # Display math
    assert convert_to_polygon_tex(r'$$\sum_{i=1}^n a_i$$') == r'$$\sum_{i=1}^n a_i$$'

    # Math with \ldots
    latex = r'$N$ integers ${K_1}, {K_2}, \ldots, {K_N}$'
    assert convert_to_polygon_tex(latex) == latex


def test_validate_after_convert_with_dollar_math():
    """Commands inside $...$ math should not be flagged after conversion."""
    from rbx.box.statements.polygon_utils import convert_to_polygon_tex

    latex = r'integer $N$ ($1 \le N \le 150$) indicating the number of balls.'
    converted = convert_to_polygon_tex(latex)
    errors = validate_polygon_tex(converted)
    assert len(errors) == 0

    latex2 = r'contains $N$ integers ${K_1}, {K_2}, \ldots, {K_N}$($1 \le K_i \le 150$ for ${i}={1}, {2}, \ldots, {N}$)'
    converted2 = convert_to_polygon_tex(latex2)
    errors2 = validate_polygon_tex(converted2)
    assert len(errors2) == 0


def test_convert_ignore_macros():
    from rbx.box.statements.polygon_utils import convert_to_polygon_tex

    # \newcommand should be stripped
    assert (
        convert_to_polygon_tex(r'\newcommand{\foo}{bar} Hello', ignore_macros=True)
        == ' Hello'
    )

    # \renewcommand should be stripped
    assert (
        convert_to_polygon_tex(r'\renewcommand{\foo}{bar} World', ignore_macros=True)
        == ' World'
    )

    # \def should be stripped
    assert convert_to_polygon_tex(r'\def\foo{bar} Text', ignore_macros=True) == ' Text'

    # Multiple macros stripped
    latex = r'\newcommand{\a}{1}\renewcommand{\b}{2} Content'
    assert convert_to_polygon_tex(latex, ignore_macros=True) == ' Content'

    # Without ignore_macros, macros are preserved
    assert r'\newcommand' in convert_to_polygon_tex(
        r'\newcommand{\foo}{bar} Hello', ignore_macros=False
    )

    # Default is False
    assert r'\newcommand' in convert_to_polygon_tex(r'\newcommand{\foo}{bar} Hello')


@pytest.mark.parametrize(
    'input_tex, expected',
    [
        # --- MATH CONVERSION ---
        # 1. Inline math
        (r'Val \( x^2 \)', r'Val $ x^2 $'),
        # 2. Display math
        (r'Val \[ y^2 \]', r'Val $$ y^2 $$'),
        # 3. Nested math (unlikely but check robust)
        (r'\( a + \[ b \] \)', r'$ a + $$ b $$$'),
        # 4. Text inside math (should not be touched? or recursively transformed?)
        (r'\( \it text \)', r'${\it text }$'),
        # --- FONT SWITCHES ---
        # 5. Simple Italic
        (r'\it Hello', r'{\it Hello}'),
        # 6. Simple Bold
        (r'\bf World', r'{\bf World}'),
        # 7. Two switches
        (r'\it One \bf Two', r'{\it One {\bf Two}}'),
        # 8. Switch then barrier (\item)
        (
            r'\begin{itemize}\item \it Text \item Next\end{itemize}',
            r'\begin{itemize}\item{\it Text }\item Next\end{itemize}',
        ),
        # 9. Switch then barrier (\section)
        (r'\it Header \section{Body}', r'{\it Header }\section{Body}'),
        # 10. Nested scopes (manual braces)
        (
            r'{\it Inside}',
            r'{{\it Inside}}',
        ),  # BraceGroup wraps content, \it wraps content inside.
        # --- COMPLEX CASES ---
        # 11. Huge list
        (
            r'\huge \begin{enumerate} \item A \end{enumerate}',
            r'{\huge\begin{enumerate}\item A \end{enumerate}}',
        ),
        # 12. Switch inside environment
        (
            r'\begin{center} \it Centered \end{center}',
            r'\begin{center}{\it Centered }\end{center}',
        ),
        # 13. Multiple barriers
        (
            r'\it A \item B \item C',
            r'{\it A }\item B \item C',
        ),  # Space consumed by A or preserved?
        # 14. Switch ending at end of file
        (r'\it Full file', r'{\it Full file}'),
        # --- SIZES ---
        # 15. Tiny
        (r'\tiny text', r'{\tiny text}'),
        # 16. Huge
        (r'\Huge BIG', r'{\Huge BIG}'),
        # 17. Mixed sizes
        (r'\small S \large L', r'{\small S {\large L}}'),
        # --- CODE BLOCKS ---
        # 18. Verbatim (should be untouched mostly)
        (
            r'\begin{verbatim} \it literal \end{verbatim}',
            r'\begin{verbatim} \it literal \end{verbatim}',
        ),
        # 19. Verb (inline) -- TexSoup parsing limitation causes this to be difficult without custom lexing
        # (r'\verb|\it|', r'\verb|\it|'),
        # --- MIXED ---
        # 20. Text with style and math
        (r'\it Math: \( x \)', r'{\it Math: $ x $}'),
        # --- GENERATED CASES (21-50) ---
        (r'\bf 21', r'{\bf 21}'),
        (r'\tt 22', r'{\tt 22}'),
        (r'\sf 23', r'{\sf 23}'),
        (r'\sl 24', r'{\sl 24}'),
        (r'\sc 25', r'{\sc 25}'),
        (r'\rm 26', r'{\rm 26}'),
        (r'\tiny 27', r'{\tiny 27}'),
        (r'\scriptsize 28', r'{\scriptsize 28}'),
        (r'\small 29', r'{\small 29}'),
        (r'\normalsize 30', r'{\normalsize 30}'),
        (r'\large 31', r'{\large 31}'),
        (r'\Large 32', r'{\Large 32}'),
        (r'\LARGE 33', r'{\LARGE 33}'),
        (r'\huge 34', r'{\huge 34}'),
        (r'\Huge 35', r'{\Huge 35}'),
        (r'\bfseries 36', r'{\bfseries 36}'),
        (r'\itshape 37', r'{\itshape 37}'),
        (r'\ttfamily 38', r'{\ttfamily 38}'),
        (r'\sffamily 39', r'{\sffamily 39}'),
        (r'\rmfamily 40', r'{\rmfamily 40}'),
        # Barriers
        (r'\it 41 \subsection{S}', r'{\it 41 }\subsection{S}'),
        (r'\it 42 \subsubsection{S}', r'{\it 42 }\subsubsection{S}'),
        (r'\it 43 \chapter{C}', r'{\it 43 }\chapter{C}'),
        (r'\it 44 \part{P}', r'{\it 44 }\part{P}'),
        (r'\it 45 \par', r'{\it 45 }\par'),  # \par is barrier
        # Nested + Math
        (r'\it 46 \( m \)', r'{\it 46 $ m $}'),
        (r'\it 47 \[ M \]', r'{\it 47 $$ M $$}'),
        # Edge Cases
        (r'\it', r'{\it}'),  # Empty switch
        (r'\it \bf', r'{\it{\bf}}'),  # Empty nested
        (r'No switch 50', r'No switch 50'),
    ],
)
def test_convert_to_polygon_tex_stress_cases(input_tex, expected):
    from rbx.box.statements.polygon_utils import convert_to_polygon_tex

    converted = convert_to_polygon_tex(input_tex)
    # Check strict equality as per stress test expectations
    assert converted.strip() == expected.strip()
