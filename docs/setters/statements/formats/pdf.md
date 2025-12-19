# PDF statements

If you already have a pre-built statement (e.g., from an external tool or an old archive), you can configure {{rbx}} to use it directly.

## Configuration

To use a PDF file as a statement:

```yaml title="problem.rbx.yml"
statements:
  - name: statement
    path: statement.pdf
    type: pdf
```

## Behavior

When the statement type is `pdf`, the build process is essentially a copy operation. The source PDF is copied to the build directory. No templating, variable substitution, or asset processing is performed on the PDF content itself.
