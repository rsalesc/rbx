# Windows and symlinks

If you are on Windows, you can use the WSL (Windows Subsystem for Linux) to run {{rbx}}. {{rbx}} makes
heavy use of symlinks to provide its features.

## Enabling symlinks in Windows

If you cannot create symlinks in Windows, you should enable Developer Mode. See Microsoft's
[Developer Mode guide](https://learn.microsoft.com/en-us/windows/advanced-settings/developer-mode).

## Git-on-Windows

If you end up using Git-on-Windows to clone your Git repository, and your repository has symlinks, by default
symlinks will not be preserved. With Developer Mode on (see
[Enabling symlinks in Windows](#enabling-symlinks-in-windows)), run the command below to enable
symlinks in Git-on-Windows **before** cloning your repo:

```bash
$ git config --global core.symlinks true
```

If you already cloned it without this setting, clone it again with symlinks enabled:

```bash
$ git clone -c core.symlinks=true <url>
```