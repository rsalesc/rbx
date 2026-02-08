# C/C++ on MacOS

## Compiler choice

Usually in MacOS, the default compiler is Clang. Even the `g++` command in the terminal is just a wrapper around Clang.

Although Clang will work just fine for most of the time, sometimes it just misbehaves completely compared to GCC. Since
online judges usually use GCC, it is a good idea to install GCC and tell {{rbx}} to use it.

To use the GNU compiler, you need to install it separately.

```sh
brew install gcc
```

But, still after installing it, you need to tell {{rbx}} to use it. Find at the end of the `brew` command which version of `g++` was installed.

For instance, if you see:

```
Installing gcc 14.2.0
```

This means that `g++-14` is probably available as a command to run in your terminal.

To tell {{rbx}} to use it, you can run `rbx config edit` and add the following to the file (replace `g++-14` with whatever version you have installed):

```yaml
command_substitutions:
  g++: g++-14
  gcc: gcc-14
```

This will tell {{rbx}} to use `gcc-14` and `g++-14` as the C and C++ compilers.

A caveat to this is that GNU GCC sanitizers do not work on MacOS. If you need sanitizers in MacOS, you will need to tell {{rbx}} to fall back to Clang when sanitizing.

```yaml
sanitizers:
  command_substitutions:
    g++: clang++
    gcc: clang
```

## Floating-point precision

If you're on a Mac with Apple Sillicon (ARM), be aware you might run into floating-point precision issues.
These two different architectures apply math optimizations differently. Whilst {{rbx}} tries its best
to disable some of them in ARM, it's not always possible to completely match the behaviour of x86.

Another important thing to notice is that `long double` is a 64-bit float in ARM, as opposed to the
standard extended 80-bit float in x86. Thus, for all effects, `long double` == `double` in ARM. If you
have solutions that are heavily dependent on the precision of `long double`, you might need to
adjust them when running on ARM, or simply accept they might fail.

