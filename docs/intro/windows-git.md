# Windows and symlinks

If you are on Windows, you can use the WSL (Windows Subsystem for Linux) to run {{rbx}}. {{rbx}} make
heavy use of symlinks under the hood to provide its functionalities.

This page describes two different issues you can face while using this tool in Windows, and how
to solve them.

## Enabling symlinks in Windows

If you cannot create symlinks in Windows, you should enable the "Developer Mode". You can find
more information in their official [documentation](https://learn.microsoft.com/en-us/windows/advanced-settings/developer-mode).

## Git-on-Windows

If you end up using Git-on-Windows to clone your Git repository, and your repository have symlinks, by default
symlinks will not be preserved. You should run the command below to enable symlinks in Git-on-Windows **before**
cloning your repo. You might need to reclone everything if you missed this step.

```bash
$ git config --global core.symlinks true
```