"""Talking to the MOJ judge through its own CLI.

`cli` is a typed wrapper over the `moj` executable; `problem_id` owns the
`.moj-id` file that binds an rbx package to a problem on the server. Nothing here
knows about `SolutionRunner` -- the runner that uses both lands on top of it.
"""
