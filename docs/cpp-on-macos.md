# C/C++ on MacOS

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

To tell {{rbx}} to use it, you can run (replace `g++-14` with whatever version you have installed):

```sh
export RBX_C_PATH=$(which gcc-14)
export RBX_CXX_PATH=$(which g++-14)
```

This will tell {{rbx}} to use `gcc-14` and `g++-14` as the C and C++ compilers.

You can also set these environment variables in your `.zshrc` or `.bashrc` file to make it permanent.

```sh
echo 'export RBX_C_PATH=$(which gcc-14)' >> ~/.bashrc
echo 'export RBX_CXX_PATH=$(which g++-14)' >> ~/.bashrc
```

