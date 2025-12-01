/*
*   Author: Roberto Sales
*
* This program is used to execute both solution and interactor and identify
* with some certainty which one finished first. It is used in the interactor_run.sh.
*/
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#define MAX_EVENTS 2
#define SOLUTION_TAG 1
#define INTERACTOR_TAG 2

struct process_args {
  int argc;
  char **argv;
  int fd;
  char *input;
  char *output;
  char *stderr;
};

struct parsed_args {
  int show_help;
  char *solution_input;      // -i
  char *solution_output;     // -o
  char *solution_stderr;     // -e
  char *interactor_stderr;   // -E
  struct process_args solution_args;
  struct process_args interactor_args;
  int verbose;
};

static void die(const char *msg) {
  fprintf(stderr, "pipe ERROR: %s\n", msg);
  exit(1);
}

static void print_help() {
  printf("Usage: pipe [OPTIONS] -- <solution_args...> = <interactor_args...>\n");
  printf("\n");
  printf("Options:\n");
  printf("  -h, --help        Show this help message\n");
  printf("  -i <file>         Input file for the solution process\n");
  printf("  -o <file>         Output file for the solution process\n");
  printf("  -e <file>         Stderr file for the solution process\n");
  printf("  -E <file>         Stderr file for the interactor process\n");
  printf("\n");
  printf("Arguments:\n");
  printf("  solution_args     Arguments for the solution process\n");
  printf("  interactor_args   Arguments for the interactor process\n");
  printf("\n");
  printf("Special substitutions:\n");
  printf("  __FD__            Replaced with the pipe file descriptor number\n");
  exit(0);
}

/* Convert waitpid(2) status to what Bash would put in $? */
int bash_like_status(int status)
{
    if (WIFEXITED(status)) {
        return WEXITSTATUS(status);          // normal exit -> exit code
    } else if (WIFSIGNALED(status)) {
        return 128 + WTERMSIG(status);       // killed by signal -> 128+signal
    } else if (WIFSTOPPED(status)) {
        // Bash doesn’t really treat "stopped" as a final status for a simple command,
        // but if you need *something*:
        return 128 + WSTOPSIG(status);
    } else {
        // continued / unknown state – pick something, or keep 0
        return 0;
    }
}

// Replace all occurrences of __FD__ with the actual fd number
static void replace_fd_in_args(char **argv, int argc, int fd) {
  char fd_str[32];
  snprintf(fd_str, sizeof(fd_str), "%d", fd);
  
  for (int i = 0; i < argc; i++) {
    char *pos = strstr(argv[i], "__FD__");
    if (pos != NULL) {
      // Allocate new string with replacement
      size_t len = strlen(argv[i]) - 6 + strlen(fd_str) + 1; // -6 for __FD__, +strlen(fd_str)
      char *new_arg = malloc(len);
      if (!new_arg)
        die("malloc failed");
      
      // Copy prefix
      size_t prefix_len = pos - argv[i];
      memcpy(new_arg, argv[i], prefix_len);
      
      // Copy fd_str
      strcpy(new_arg + prefix_len, fd_str);
      
      // Copy suffix
      strcpy(new_arg + prefix_len + strlen(fd_str), pos + 6);
      
      free(argv[i]);
      argv[i] = new_arg;
    }
  }
}

static struct parsed_args parse_arguments(int argc, char *argv[]) {
  struct parsed_args result;
  memset(&result, 0, sizeof(result));
  
  // Find delimiters -- and =
  int delimiter1_idx = -1; // Index of "--"
  int delimiter2_idx = -1; // Index of "="
  
  // Parse first block (program flags)
  int i = 1; // Skip program name
  while (i < argc) {
    if (strcmp(argv[i], "--") == 0) {
      delimiter1_idx = i;
      break;
    }
    
    // Parse flags here
    if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
      result.show_help = 1;
      print_help();
    }
    else if (strcmp(argv[i], "-i") == 0) {
      if (i + 1 >= argc) {
        die("-i flag requires an argument");
      }
      result.solution_input = strdup(argv[i + 1]);
      if (!result.solution_input)
        die("strdup failed");
      i++; // Skip the argument
    }
    else if (strcmp(argv[i], "-o") == 0) {
      if (i + 1 >= argc) {
        die("-o flag requires an argument");
      }
      result.solution_output = strdup(argv[i + 1]);
      if (!result.solution_output)
        die("strdup failed");
      i++; // Skip the argument
    }
    else if (strcmp(argv[i], "-e") == 0) {
      if (i + 1 >= argc) {
        die("-e flag requires an argument");
      }
      result.solution_stderr = strdup(argv[i + 1]);
      if (!result.solution_stderr)
        die("strdup failed");
      i++; // Skip the argument
    }
    else if (strcmp(argv[i], "-E") == 0) {
      if (i + 1 >= argc) {
        die("-E flag requires an argument");
      }
      result.interactor_stderr = strdup(argv[i + 1]);
      if (!result.interactor_stderr)
        die("strdup failed");
      i++; // Skip the argument
    } else if (strcmp(argv[i], "-v") == 0) {
      result.verbose = 1;
    }
    // Add more flag parsing here as needed
    // else if (strcmp(argv[i], "--flag") == 0) {
    //   // Handle flag
    // }
    else {
      fprintf(stderr, "Unknown option: %s\n", argv[i]);
      die("Invalid argument");
    }
    
    i++;
  }
  
  if (delimiter1_idx == -1) {
    die("Missing '--' delimiter for solution arguments");
  }
  
  // Find "=" delimiter
  for (int j = delimiter1_idx + 1; j < argc; j++) {
    if (strcmp(argv[j], "=") == 0) {
      delimiter2_idx = j;
      break;
    }
  }
  
  if (delimiter2_idx == -1) {
    die("Missing '=' delimiter for interactor arguments");
  }
  
  // Parse solution arguments (between -- and =)
  int solution_argc = delimiter2_idx - delimiter1_idx - 1;
  if (solution_argc <= 0) {
    die("No solution arguments provided");
  }
  
  result.solution_args.argc = solution_argc;
  result.solution_args.argv = malloc(sizeof(char *) * (solution_argc + 1));
  if (!result.solution_args.argv)
    die("malloc failed");
  
  for (int j = 0; j < solution_argc; j++) {
    result.solution_args.argv[j] = strdup(argv[delimiter1_idx + 1 + j]);
    if (!result.solution_args.argv[j])
      die("strdup failed");
  }
  result.solution_args.argv[solution_argc] = NULL; // NULL-terminate for execv
  
  // Parse interactor arguments (after =)
  int interactor_argc = argc - delimiter2_idx - 1;
  if (interactor_argc <= 0) {
    die("No interactor arguments provided");
  }
  
  result.interactor_args.argc = interactor_argc;
  result.interactor_args.argv = malloc(sizeof(char *) * (interactor_argc + 1));
  if (!result.interactor_args.argv)
    die("malloc failed");
  
  for (int j = 0; j < interactor_argc; j++) {
    result.interactor_args.argv[j] = strdup(argv[delimiter2_idx + 1 + j]);
    if (!result.interactor_args.argv[j])
      die("strdup failed");
  }
  result.interactor_args.argv[interactor_argc] = NULL; // NULL-terminate for execv
  
  return result;
}

void fill_in_solution_stdio(struct parsed_args *args) {
  if (args->solution_stderr) {
    args->solution_args.stderr = args->solution_stderr;
  }
}

void fill_in_interactor_stdio(struct parsed_args *args) {
  if (args->solution_input) {
    args->interactor_args.output = args->solution_input;
  }
  if (args->solution_output) {
    args->interactor_args.input = args->solution_output;
  }
  if (args->interactor_stderr) {
    args->interactor_args.stderr = args->interactor_stderr;
  }
}

void create_pipe(int *pip) {
  if (pipe(pip) == -1)
    die("pipe failed");
  // Avoid leaking file descriptors to children.
  fcntl(pip[0], F_SETFD, fcntl(pip[0], F_GETFD) | FD_CLOEXEC);
  fcntl(pip[1], F_SETFD, fcntl(pip[1], F_GETFD) | FD_CLOEXEC);
}

int run_process(struct process_args *args) {
  // Allow the child to inherit the file descriptor.
  fcntl(args->fd, F_SETFD, fcntl(args->fd, F_GETFD) & ~FD_CLOEXEC);
  int pid = fork();
  if (pid == 0) {
    if (args->input) freopen(args->input, "r", stdin);
    if (args->output) freopen(args->output, "w", stdout);
    if (args->stderr) freopen(args->stderr, "w", stderr);
    execv(args->argv[0], args->argv);
    die("execv failed");
  }
  // Prevent the child from inheriting the file descriptor.
  fcntl(args->fd, F_SETFD, fcntl(args->fd, F_GETFD) | FD_CLOEXEC);
  close(args->fd);
  return pid;
}

int main(int argc, char *argv[]) {
  // Parse arguments
  struct parsed_args args = parse_arguments(argc, argv);
  
  // Create pipes
  int p1_pipe[2];
  int p2_pipe[2];
  create_pipe(p1_pipe);
  create_pipe(p2_pipe);
  
  // Set up file descriptors for each process
  args.solution_args.fd = p1_pipe[1];
  args.interactor_args.fd = p2_pipe[1];
  
  // Replace __FD__ placeholders with actual fd numbers
  replace_fd_in_args(args.solution_args.argv, args.solution_args.argc, p1_pipe[1]);
  replace_fd_in_args(args.interactor_args.argv, args.interactor_args.argc, p2_pipe[1]);
  
  // Fill in stdio files
  fill_in_solution_stdio(&args);
  fill_in_interactor_stdio(&args);
  
  // Start both processes
  int solution_pid = run_process(&args.solution_args);
  int interactor_pid = run_process(&args.interactor_args);

  int ep = epoll_create1(0);
  if (ep == -1)
    die("epoll_create1 failed");

  struct epoll_event ev;
  memset(&ev, 0, sizeof(ev));

  ev.events = EPOLLHUP;
  ev.data.u32 = SOLUTION_TAG; // tag for P1
  if (epoll_ctl(ep, EPOLL_CTL_ADD, p1_pipe[0], &ev) == -1)
    die("epoll_ctl solution");

  ev.events = EPOLLHUP;
  ev.data.u32 = INTERACTOR_TAG; // tag for P2
  if (epoll_ctl(ep, EPOLL_CTL_ADD, p2_pipe[0], &ev) == -1)
    die("epoll_ctl interactor");

  // Wait for the first of P1/P2 to "disappear"
  struct epoll_event events[MAX_EVENTS];
  int n = epoll_wait(ep, events, MAX_EVENTS, -1);
  if (n == -1)
    die("epoll_wait");
  if (!(events[0].events & EPOLLHUP)) {
    fprintf(stderr, "epoll_wait: no EPOLLHUP event from %d\n", events[0].data.u32);
    die("epoll_wait: no EPOLLHUP event");
  }
  int first_tag = events[0].data.u32;
  if (args.verbose) fprintf(stderr, "first tag: %d\n", first_tag);

  int solution_status = 0;
  int interactor_status = 0;

  for (int i = 0; i < 2; i++) {
    int pid = (i ^ (first_tag == SOLUTION_TAG)) ? solution_pid : interactor_pid;
    int status;
    if (waitpid(pid, &status, 0) == -1)
      die("waitpid failed");
    if (pid == solution_pid) {
      solution_status = bash_like_status(status);
      if (args.verbose) fprintf(stderr, "solution status: %d\n", solution_status);
      if (solution_status) if (kill(interactor_pid, SIGTERM)) {
        fprintf(stderr, "term interactor failed: %s\n", strerror(errno));
      }
    } else {
      interactor_status = bash_like_status(status);
      if (args.verbose) fprintf(stderr, "interactor status: %d\n", interactor_status);
      if (interactor_status) if (kill(solution_pid, SIGTERM)) {
        fprintf(stderr, "term solution failed: %s\n", strerror(errno));
      }
    }
  }

  fprintf(stdout, "%d\n", first_tag);
  fprintf(stdout, "%d\n", solution_status);
  fprintf(stdout, "%d\n", interactor_status);
  exit(0);
}