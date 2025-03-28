# Stack limit

When developing programming competition problems locally, it's often the case we hit the stack limit configured in our system.

This is usually a problem because in modern online judges, the stack limit is configured to be as large as 256 MiB, but often the default configuration for Unix-like systems is way smaller than that.

The disparity can usually cause some friction, because it's really hard to identify that a solution crashed because it exceeded the stack limit, and not because of some other reason. Thus, it's usually a good practice to increase the stack limit as much as possible to avoid the problem.

You can check your current stack limit by running `ulimit -s` in your terminal. Also, you can check even more details about resource limits by running `sudo launchctl limit`, which will show something like this:

```
        cpu         unlimited      unlimited      
        filesize    unlimited      unlimited      
        data        unlimited      unlimited      
        stack       8372224        67092480       
        core        0              unlimited      
        rss         unlimited      unlimited      
        memlock     unlimited      unlimited      
        maxproc     2666           4000           
        maxfiles    256            unlimited
```

Notice we have two columns for each resource limit. The first column indicates a soft limit -- in this example, 8 MiB --, and the second column indicates a hard limit -- in this example, 64 MiB. Usually, hard limits are a bit hard to configure, but soft limits can be easily increased to match the hard limit through the `ulimit` command.

!!! note
    8 MiB is a really small and dangerous stack limit: it's not uncommon for a DFS with a handful of parameters in a big graph to exceed that limit. On the other hand, 64 MiB is usually enough for most problems.

## Increase the soft stack limit

To increase the stack limit to the maximum allowed (which will match the hard limit), you can run:

```
ulimit -s unlimited
```

To ensure you're not bitten by this issue so easily, {{rbx}} will complain if you try to run code
while your soft stack limit is less than your hard stack limit.

Do not worry, the fix is really simple and will be shown along the error message.

!!! tip
    You should ensure the lines added to the file are definitely after the lines where `pipx` paths are added to `$PATH$`, otherwise the `rbx` command will not be found.

## Increase the hard stack limit

Sometimes, the hard stack limit is also too small. In this case, you can increase the hard stack limit in different ways depending on your system.

### On Linux

Open `/etc/security/limits.conf` and add the following lines:

```
* stack soft <soft_limit_in_bytes>
* stack hard <hard_limit_in_bytes>
```

This configuration should persist after a reboot.

### On MacOS

Run the following command in your terminal:

```
sudo launchctl limit stack <soft_limit_in_bytes> <hard_limit_in_bytes>
```

This configuration will NOT persist after a reboot, but will persist across terminals.


