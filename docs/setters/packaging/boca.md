# Packaging: BOCA

{{rbx}} provides a command to build packages for BOCA.

```bash
rbx package boca
```

{{ asciinema("3aYdLnJVUS6dUaF9TWg6UkFMz") }}

Or, if you want to build the package for all problems in your contest:

```bash
rbx contest each package boca
```

Both **batch** problems and **interactive** problems are supported.

## Interactive problems

Interactive problems can be easily packaged for BOCA with {{rbx}}. There are some limitations to it, though:

- The BOCA package needs a checker. In case you don't provide one, the tool will automatically generate a dummy one,
  one that returns AC for all inputs, as long as the interactor finishes successfully.
- The messages exchanged between the interactor and the solution will not be captured, and thus will not be visible
  in the BOCA UI. If you want to inspect the interaction between them, you have to download the participant's
  solution and run it locally.

## Uploading to BOCA

You can upload the package to BOCA by setting the `--upload` / `-u` flag.

```bash
rbx package boca -u
```

Or you can use the contest-level commands below.

```bash
# Will upload all problems in the contest
rbx contest each package boca -u

# Will upload only problem A
rbx contest on A package boca -u

# Will upload problems A to C
rbx contest on A-C package boca -u

# Will upload problems A and C
rbx contest on A,C package boca -u
```

{{ asciinema("onJXQDVPELqn2kITmCrbkJeCX", speed=3) }}

For that to work, you have to instruct {{rbx}} on how to connect to the BOCA server.

{{rbx}} expects you to have set three environment variables, which you can, for instance, keep in your `.bashrc` or `.zshrc` files:

```bash
export BOCA_USERNAME="admin_username"
export BOCA_PASSWORD="admin_password"
export BOCA_BASE_URL="https://your.boca.com/boca"
```

Notice the configured user must correspond to an admin of your contest, so {{rbx}} will have permissions to upload
the package. Also, make sure the correct contest is activated in the BOCA server before running the command.


## Troubleshooting

### Upload is taking too long, or an error is being reported

BOCA packages are uploaded to the server via HTTP. By default, BOCA servers (actually, PHP servers) are configured
with a really tight limit for uploaded file sizes. If you are running into this issue, you can try to increase the
limit by setting the `upload_max_filesize` and the `post_max_size` directives in your `php.ini` file.

For BOCA installations done through the official Maratona Ubuntu PPA, you can find the configuration file in
`/etc/php/8.1/fpm/php.ini`, and then restart the PHP service with `sudo service php8.1-fpm restart`.

If you want to give a shot at fixing this with a bash script, try running:

```bash
sudo sed -i 's/upload_max_filesize = .*/upload_max_filesize = 200M/' /etc/php/8.1/fpm/php.ini
sudo sed -i 's/post_max_size = .*/post_max_size = 200M/' /etc/php/8.1/fpm/php.ini
sudo sed -i 's/memory_limit = .*/memory_limit = 256M/' /etc/php/8.1/fpm/php.ini
sudo service php8.1-fpm restart
```

!!! danger
    These limits are there for a reason, and you should only change them if you know what you're doing.
    Allowing big post sizes can open the door for malicious users to take advantage of that.
    
    Try setting it to the smallest value you need to be able to upload your packages.

!!! warning
    Another option, often easier but sometimes undesirable, is to make sure your packages are not too big. Big
    packages will usually pose a problem if you're trying to fix a package during the contest with a slow connection.

### I removed a problem from the contest, but it still appears in BOCA

{{rbx}} does not remove problems from BOCA automatically, as this is a disruptive change. You will have to remove
the problem manually from BOCA.

Also notice that, when you rearrange problems in the contest (for instance, add a problem C, and move all problems
after C one position ahead), {{rbx}} will override the old C problem with the new one.

### I'm seeing a different verdict in BOCA than the one I got in {{rbx}}

It's expected that some verdicts are different in BOCA, especially because the sandboxes used by both platforms
are not exactly the same.

For instance, you can see runtime errors vs. memory limit exceeded, or differences like this.

If you see a difference that you think is not justifiable, please let us know by opening an issue on our {{repo}}.