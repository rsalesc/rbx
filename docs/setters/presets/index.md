# Presets

!!! note
    This documentation is mainly targeted at head setters trying to create a contest
    from scratch.

    If you're just a setter that wants to contribute to an already existing contest,
    you can probably just clone the repository the head setters shared with you and skip
    this documentation altogether.

Presets is a feature that allows head setters to create a contest template that can be reused
across multiple contests.

A preset consists of four different pieces:

- A **contest template**: simply, a contest folder with some sensible defaults set that will
  be used to bootstrap a contest based on this preset
- A **problem template**: a problem folder with some sensible defaults set that will
  be used to bootstrap each problem based on this preset
- An **environment**: a configuration file that will be inherited by contests and problems
  created from this preset, and that {{rbx}} will use to configure its execution environment
- A **preset definition**: a `preset.rbx.yml` file that will be used to define the preset
  and its dependencies.

## Why a preset?

Presets strongly encourage code reuse across different contests. Besides that, it provides
a way to standardize the contest environment across different contests, making it easier
for setters to focus on creating the contest instead of configuring the environment.

Also, it makes it easier for setters to create new problems in a contest, offering a way for
the head setter to define a starting point for the problem.

Also, if the head setter wants to change the preset at some point, presets offer a way
to synchronize the changes across all the problems and contests that use the preset.

## Creating a preset

Creating a preset is a multi-step process that starts when the head setter runs the
`rbx preset create` command. By default, the command will create a new preset based
on {{rbx}} default preset.

```bash
rbx presets create
```

The command will prompt you for the name of the preset, and a GitHub repository URI that
can be used to reference to it.

```bash
└── your-preset-name
    ├── contest # (1)!
    ├── problem # (2)!
    ├── env.rbx.yml # (3)!
    └── preset.rbx.yml # (4)!
```

1. The contest template. This folder will be used to bootstrap each contest created from
   this preset.
2. A problem template. This folder will be used to bootstrap each problem created from
   this preset.
3. An environment file. This file will be used to configure the execution environment
   of {{rbx}} to be used in the contest.
4. A preset definition. This file will be used to define the preset and its dependencies.

The GitHub URI will be an unique identifier of your preset, and
can be used by other {{rbx}} users to fetch your preset from there if you decide to share
it publicly.

You can start from a preset of your own by specifying the `-p` flag.

!!! tip
    If you want to start from a preset of your own, you can do so by specifying the `-p`
    flag.

    ```bash
    rbx presets create -p your-base-preset
    ```

### Setting up the problem template

You can go to the problem template and modify it to your liking: package structure,
the `problem.rbx.yml` file, default testlib components, statement templates, etc. Everything
can be customized to fulfill your requirements.

Every problem created from this preset will be a clone of this folder, except for the folder name
and the `name` field of the `problem.rbx.yml` file, which will be changed to match your problem name.

!!! tip
    You can run {{rbx}} commands freely inside the problem template folder to test your template:
    any {{rbx}} internal folders will be ignored when inheriting from the preset.

### Setting up the contest template

You can go to the contest template and modify it to your liking: statement templates, `contest.rbx.yml` file,
etc. Everything can be customized to fulfill your requirements.

Usually, the contest template should have no problems initially. One should add problems with
`rbx contest add` after the contest has been created.

Every contest created from this preset will be a clone of this folder, except for the folder name
and the `name` field of the `contest.rbx.yml` file, which will be changed to match your contest name.

!!! tip
    You can run {{rbx}} commands freely inside the contest template folder to test your template:
    any {{rbx}} internal folders will be ignored when inheriting from the preset.

### Setting up the environment

The environment file will be used to configure the execution environment of {{rbx}} to be used
in the contest.

This file is rather complex, and its full reference documentation can be found [here](../reference/env.md).

You can usually get away with the environment used by the `default` preset, which is
a good starting point for most contests. You can check its code [here](https://github.com/rsalesc/rbx/blob/main/rbx/resources/presets/default/env.rbx.yml).

### Setting up the preset definition

The preset definition file is a `preset.rbx.yml` file that will be used to define the preset
and its dependencies.

TODO: write this section

## Using a preset

Presets can be used both when creating a contest or when creating a problem. Below
we detail all the commands where it can be used.

```bash
# Create a contest from a preset.
rbx contest create -p your-preset

# Initialize a contest (in the current directory) from a preset.
rbx contest init -p your-preset

# Add a problem to a contest (that already has its own preset), using the very same preset.
rbx contest add

# Create a standalone problem from a preset.
rbx create -p your-preset
```

In all variants above, a `.local.rbx` folder will be created at the root of the package. This folder stores a copy of the
preset, snapshotted at the moment the package was created. This way, your package has its own copy of the preset,
and you can either

1. Modify it at will, and those changes will not be reflected in the original preset;
2. Sync it to the original preset whenever you want.

If you modify your `.local.rbx` folder, but has already created some problems inside your contest that you
want to sync with the preset, you can do so by running `rbx presets sync` inside your contest folder.

This will sync all packages that use this preset with its newest changes. In other words, it will create missing
symlinks, and ask you if normal tracked files should be overridden or not.

## Sharing a preset publicly

You can share your preset publicly by uploading it to a GitHub repository. If your repository is
`<your-organization>/<your-preset-name>`, other uses can create a package from it by using

```bash
rbx contest create -p <your-organization>/<your-preset-name>
```

The preset will be cloned automatically, and then used as normal.

## Sharing a preset privately

You can share your preset privately, either through Git repositories or through other means. To initialize
a contest from a private preset, you can do the following:

```bash
mkdir my-new-contest
cd my-new-contest

# Clone the preset into .local.rbx
git clone https://github.com/my-organization/my-preset .local.rbx

# Initialize the contest
rbx contest init
```

This will initialize the contest from the `.local.rbx` preset, which you can initialize from a private
data source of your own.

