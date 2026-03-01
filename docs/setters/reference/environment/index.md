# Environment

An environment file is a YAML configuration file that describes the environment in which {{rbx}} will execute
your code.

The [`Environment`][rbx.box.environment.Environment] class is used to describe the environment in which the code will be executed. You can follow the schema of this class to figure out everything you can
configure in the environment file, but here we'll describe the most common fields.

## Compilation configuration

You can define a few default settings for compilation by using the `defaultCompilation` field.

You can look at the [`CompilationConfig`][rbx.box.environment.CompilationConfig] class for more details of
what you can do, but here's an example with a few useful settings:

```yaml
defaultCompilation:
  # Defines a few default limits when compiling in the sandbox.
  sandbox:
    timeLimit: 10000 # 10 seconds
    wallTimeLimit: 10000 # 20 seconds
    memoryLimit: 1024 # 1gb
```

Usually, the default values here are enough, but you can customize this for your needs. For instance,
if you have a very slow computer at hand, you might want to increase the limits to ensure the compilers
have the time to do their job.

## Default execution configuration

You can establish similar limits for code execution by using the `defaultExecution` field, by using the
[`ExecutionConfig`][rbx.box.environment.ExecutionConfig] class.

```yaml
defaultExecution:
  # Defines a few default limits when running programs in the sandbox.
  sandbox:
    timeLimit: 10000 # 10 seconds
    wallTimeLimit: 10000 # 20 seconds
    memoryLimit: 1024 # 1gb
```

Notice these limits are language agnostic, and problem agnostic. This means you should set this to a
value larger than any limit you expect for any problem. This is mostly used to ensure programs that
eat too much memory or take too long to finish, but don't have limits applied to them, don't hang forever
or crash your system. Examples are checkers, validators, etc.

## Languages

The `languages` field is used to define the languages supported by the environment. This is
a list of [`EnvironmentLanguage`][rbx.box.environment.EnvironmentLanguage] objects, which you can
look at the schema for more details.

Here's an example of a language definition:

```yaml
languages:
  - name: "cpp" # (1)!
    readableName: "C++17" # (2)!
    extension: "cpp" # (3)!
    compilation: # (4)!
      commands:
        - "g++ -std=c++20 -O2 -o {executable} {compilable}"
    execution: # (5)!
      command: "./{executable}"
    fileMapping: # (6)!
      compilable: "compilable.cpp"
```

1. The `name` field is the name of the language, which will be used to identify the language when
   explicitly specifying the language of a solution or other code item in your packages.
2. The `readableName` field is the name of the language as it will be displayed to you.
3. The `extension` field identifies the extension of files that will be automatically inferred
   to have been written in this language.
4. The `compilation` field is a [`CompilationConfig`][rbx.box.environment.CompilationConfig] object where
   you can specify how code in this language should be compiled. Notice the use of the `{executable}` and `{compilable}` placeholders.
5. The `execution` field is an [`ExecutionConfig`][rbx.box.environment.ExecutionConfig] object where
   you can specify how code in this language should be executed.
6. The `fileMapping` field is a [`FileMapping`][rbx.box.environment.FileMapping] object where
   you can specify how files should be named when copied into the sandbox. Notice you can refer to these
   files by using the `{file}` placeholder in the `compilation` and `execution` fields.

## File mapping

The `fileMapping` field is a [`FileMapping`][rbx.box.environment.FileMapping] object where
you can specify how files should be named when copied into the sandbox.

Notice you can refer to these files by using the `{file}` placeholder in the `compilation` and `execution` fields when configuring new
languages.

Here's an example of a file mapping for the Java language, and how you would
consume them in the `compilation` and `execution` fields:

```yaml
languages:
  - name: "java"
    readableName: "Java"
    extension: "java"
    compilation:
      commands:
        - "javac -Xlint -encoding UTF-8 {compilable}"
        - "jar cvf {executable} @glob:*.class"
    execution:
      command:
        "java -Xss100m -Xmx{{memory}}m -Xms{{initialMemory}}m -cp {executable}
        Main"
    fileMapping:
      compilable: "Main.java"
      executable: "Main.jar"
```

Notice how we use the `{compilable}` and `{executable}` placeholders in the `compilation` and `execution` fields,
and name them appropriately in the `fileMapping` field.

## Command variables

Also, notice you have a few variables that are available to you in the `compilation` and `execution` fields.

- `{compilable}`: The path to the file that should be compiled.
- `{executable}`: The path to the file that should be executed.
- `{stdin}`: The path to the file that should be used as standard input.
- `{stdout}`: The path to the file that should be used as standard output.
- `{stderr}`: The path to the file that should be used as standard error.
- `{memory}`: The memory limit for the sandbox.
- `{initialMemory}`: The initial memory for the sandbox.
- `{javaClass}`: The name of the Java class to be executed.

And you also have available to you a `@glob:...` command that is expanded into a list of files that match the glob pattern. This is particularly useful for languages that need multiple files to be compiled or executed (such as Java in the example above).

## Timing estimation

Last but not least, you can configure a timing formula to be used when estimating time limits after running
`rbx time` or `rbx run -t`.

By default, the formula is `step_up(max(fastest * 3, slowest * 1.5), 100)`. The following variables/functions are available to you:

- `fastest`: The time of the fastest solution among all AC solutions.
- `slowest`: The time of the slowest solution among all AC solutions.
- `step_up(value, step)`: Returns the value rounded up to the nearest multiple of `step`.
- `step_down(value, step)`: Returns the value rounded down to the nearest multiple of `step`.
- `max(a, b)`: Returns the maximum of `a` and `b`.
- `min(a, b)`: Returns the minimum of `a` and `b`.

You might specify a different formula by using the `timing` field:

```yaml
timing:
  formula: "step_up(max(fastest * 2, slowest * 1.5), 100)"
```




