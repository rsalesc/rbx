# Visualizers

Visualizers are small programs that transform a raw testcase input (and optionally its output) into a human-readable format, such as an image or an interactive HTML page.

They are extremely useful for debugging geometry problems, game-theory problems, or any problem where the input is a complex structure that is hard to parse mentally.

For instance, finding a bug in a Convex Hull algorithm is much easier if you can *see* the points and the hull, rather than staring at a list of coordinates.

## Configuration

You can configure a global visualizer for your problem in the `problem.rbx.yml` file, specifically in the `visualizer` field.

```yaml title="problem.rbx.yml"
# ...
visualizer:
  path: visualizers/visualizer.py
  extension: 'png'
```

The configuration above tells {{rbx}} that:

1.  The visualizer source code is located at `visualizers/visualizer.py`.
2.  The visualizer produces files with the `.png` extension.

The visualizer script itself receives the following arguments:

```bash
./visualizer <visualization-path> <input-file> [<output-file>] [<answer-file>]
```

-   `<visualization-path>`: The path where the visualizer should write the visualization.
-   `<input-file>`: The path to the input file of the testcase.
-   `<output-file>` (optional): The path to the output file of the testcase (participant's output).
-   `<answer-file>` (optional): The path to the answer file of the testcase (jury's output).

### Input vs Solution Visualizers

{{rbx}} distinguishes between two types of visualizers:

-   **Input visualizer**: Used to visualize a testcase -- and only the testcase. It receives only the `<input-file>` and the `<output-file>` is set to the model solution's output, if it is available.
-   **Solution visualizer**: Used to visualize the *output* of a solution in the context of a given testcase. Besides
the `<input-file>`, it also receives an `<output-file>` which is the output of a solution for a testcase. Besides that, it can also receive an `<answer-file>`, pointing to the expected answer for this test,
if it is available.

Let's use as an example a convex hull problem. Think of a **input visualizer** as being useful for
seeing the points in the plane, as well as the expected convex hull polygon. **Solution visualizers**
can then be used to render the polygon produced by a specific solution. 

They're quite similar, but it's useful to allow them to be configured separately. By default, the `visualizer` field configures **both** input and solution visualizers. If you want to configure them separately, or if your solution visualizer is different from the input visualizer, you can use the `solutionVisualizer` field.

```yaml title="problem.rbx.yml"
solutionVisualizer:
  path: 'visualizers/solution_visualizer.py'
  extension: 'png'
```

### Answer sources (`answer_from`)

Sometimes, the raw output of the model solution is not enough for the visualizer.

For instance, in a convex hull problem, you might be asked to print its area -- a single number. This
number can't really be used to render anything useful for debugging. The convex hull points, on the other
hand, are much more useful.

You can modify your model solution to output the trace to `stderr`, and then tell the visualizer to read the answer from `stderr`:

```yaml title="problem.rbx.yml"
visualizer:
  path: 'visualizers/visualizer.py'
  extension: 'png'
  answer_from: 'stderr'
```

!!! warning
    Be careful when using `stderr` to output the visualizable output. If you print too much into
    the `stderr`, your program might slow down. In these cases, prefer the solution below.

Alternatively, you can specify a separate program that generates the answer for the visualizer:

```yaml title="problem.rbx.yml"
visualizer:
  path: 'visualizers/visualizer.py'
  extension: 'png'
  answer_from:
    path: 'visualizers/generate_answer.cpp'
    stderr: false  # Set to true if your program outputs into stderr of stdout
```

## Writing a visualizer

Visualizers can be written in any language supported by {{rbx}}.

For Python, a simple visualizer structure would look like this:

```python
import sys

try:
    import matplotlib.pyplot as plt
except ImportError:
    print("Matplotlib is not installed. Please install it with: pip install matplotlib")
    sys.exit(1)

dest_path, input_path = sys.argv[1], sys.argv[2]

# Read points (x, y) from input file
X, Y = [], []
with open(input_path) as f:
    # Skip header (usually N) if necessary, or just read everything
    for line in f:
        parts = line.split()
        if len(parts) >= 2:
            X.append(float(parts[0]))
            Y.append(float(parts[1]))

# Plot
plt.scatter(X, Y)
plt.title("Points Visualization")

# Save to destination
plt.savefig(dest_path)
```

!!! tip
    In the LLM era, visualizers are particularly easy to be generated.

!!! tip
    Visualizers often require external libraries to function properly. Make sure that you fail gracefully
    if a required library is not available. Other setter facing this issue will be able to quickly see
    a dependency is missing and fix it.

## Usage

### In `rbx ui`

The most common way to use visualizers is through the **Test Explorer UI**, accessible via `rbx ui`.

-   Press <kbd>v</kbd> to run the **input visualizer** for the selected testcase.
-   Press <kbd>Shift</kbd>+<kbd>v</kbd> (or <kbd>V</kbd>) to run the **solution visualizer** for the selected testcase (requires a solution to be selected).

The visualization will be generated and automatically opened in the program associated with the
visualizer's output extension. For instance, if the visualizer produces a `.png` file, it will be
opened in your default image viewer.

### In `rbx build`

You can also batch-generate visualizations for all testcases during the build process:

```bash
rbx build --visualize
```

This will generate input visualizations for all testcases and store them in the build directory, typically under `build/tests/<testgroup>/visualization`.
