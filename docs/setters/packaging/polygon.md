# Packaging: Polygon

{{rbx}} provides a command to build packages for Polygon. The Polygon format supports
two types of packages: problem packages and contest packages.

## Problem packages

Problem packages are built by running the following command:

```bash
rbx package polygon
```

Or, if you want to build a problem package for each problem in your contest:

```bash
rbx contest each package polygon
```

## Contest packages

There's also a contest-level command for building a contest package:

```bash
rbx contest package polygon
```

This command will build a single `.zip` file with all problems in the contest.

## Uploading to Codeforces Gym

There are two totally different ways of uploading Polygon packages to Codeforces Gym.

### Using the Taskbook FTP

You can upload a contest package to Codeforces Gym by first building it with the command above, and then
using the Codeforces Taskbook FTP (taskbook.codeforces.com) to upload your zip file to your contest.

You can read more about the Taskbook by enabling coach mode, creating a new contest in the Gym, and looking
at the "Coach mode on" section on the right side of the contest page. It will look like the image below:

![Coach mode on](taskbook.png)

Follow the instructions to upload your contest ZIP.

!!! note
    By uploading through the Taskbook, you'll only get PDF statements. That is not a limitation of {{rbx}},
    but rather the way Codeforces Gym and Taskbook work (probably for safety reasons as otherwise people could
    inject arbitrary HTML code into Codeforces).

    If you prefer HTML statements, you can use the option below.

!!! danger
    Quite often the Taskbook FTP will be down. It seems this endpoint is not very reliable anymore.
    Refer to the option below, which is a bit more complicated but more reliable.

### Using the Polygon API

You can also upload your problem packages to Polygon, gather them into a Polygon contest, and import them in the Gym.

This is a process that is a bit more complicated, and has a few limitations, but that usually gives you a better result.
The pros of using this method are:

- You'll get a Polygon problem instance for each problem in your contest. This means you can access the problem in Polygon,
  run some custom invocations, and even tune the time limit of each problem to Codeforces' machines.
- You can get HTML statements which render natively in Codeforces.
- Does not depend on the flaky Taskbook FTP.

Follow the step-by-step guide below to get your contest up in the Gym.

#### Step 1: Get a Polygon API key

#### Step 2: Upload all your problems to Polygon using the API

#### Step 3: Create a new Polygon contest with all the problems

#### Step 4: (Optional) Tune your time limits and statements to Polygon

#### Step 5: Create a contest in the Gym and import the Polygon contest


## Troubleshooting

### I'm getting an error about the checker

