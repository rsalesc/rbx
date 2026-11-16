// Fanout interactors: talk to several copies of the solution at once.
//
// rbx (and CMS) call the interactor as
//   interactor <input> <output> <from_0> <to_0> ... <from_{N-1}> <to_{N-1}>
// where from_i carries what process i writes and to_i what it reads.
#if defined(_TESTLIB_H_) && !defined(RBX_PUBLIC) && !defined(_WIN32)
#include <cerrno>
#include <csignal>
#include <cstring>
#include <fcntl.h>
#include <memory>
#include <ostream>
#include <streambuf>
#include <string>
#include <unistd.h>
#include <vector>

namespace rbx {
namespace fanout {
namespace detail {

// A std::streambuf over a file descriptor, flushed on std::endl / flush.
class FdBuf : public std::streambuf {
public:
  explicit FdBuf(int fd) : fd_(fd) { setp(buf_, buf_ + sizeof buf_); }
  ~FdBuf() override { closeFd(); }

  void closeFd() {
    flushBuffer();
    if (fd_ >= 0) {
      ::close(fd_);
      fd_ = -1;
    }
  }

protected:
  int overflow(int ch) override {
    if (flushBuffer() < 0) {
      return traits_type::eof();
    }
    if (ch != traits_type::eof()) {
      *pptr() = static_cast<char>(ch);
      pbump(1);
    }
    return traits_type::not_eof(ch);
  }

  int sync() override { return flushBuffer() < 0 ? -1 : 0; }

private:
  int flushBuffer() {
    const char *p = pbase();
    int status = 0;
    while (fd_ >= 0 && p < pptr()) {
      ssize_t k = ::write(fd_, p, static_cast<size_t>(pptr() - p));
      if (k < 0) {
        if (errno == EINTR) {
          continue;
        }
        // The process is gone. SIGPIPE is ignored, so this is how it shows;
        // its missing answer is what the interactor reports.
        status = -1;
        break;
      }
      p += k;
    }
    setp(buf_, buf_ + sizeof buf_);
    return status;
  }

  int fd_;
  char buf_[1 << 16];
};

struct Channel {
  std::unique_ptr<InStream> from;
  std::unique_ptr<FdBuf> buf;
  std::unique_ptr<std::ostream> to;
};

inline std::vector<Channel> &channels() {
  static std::vector<Channel> value;
  return value;
}

// The descriptor K named by a "/dev/fd/K" path, or -1.
inline int inheritedFd(const char *path) {
  const char *prefix = "/dev/fd/";
  size_t len = std::strlen(prefix);
  if (std::strncmp(path, prefix, len) != 0 || path[len] == '\0') {
    return -1;
  }
  int fd = 0;
  for (const char *p = path + len; *p != '\0'; p++) {
    if (*p < '0' || *p > '9' || fd > 1000000) {
      return -1;
    }
    fd = fd * 10 + (*p - '0');
  }
  return fd;
}

inline int openChannel(const char *path, int flags) {
  // A "/dev/fd/K" channel is a pipe end the interactor inherited. Take K over
  // instead of opening the path: opening it would leave K open next to the new
  // descriptor (Linux reopens the pipe, macOS duplicates K), and closing only
  // one of them would never show the process end of file.
  int fd = inheritedFd(path);
  if (fd >= 0) {
    int mode = ::fcntl(fd, F_GETFL);
    if (mode < 0) {
      quitf(_fail, "rbx: fanout channel %s is not an open descriptor", path);
    }
    int access = mode & O_ACCMODE;
    if (access != O_RDWR && access != (flags & O_ACCMODE)) {
      quitf(_fail, "rbx: fanout channel %s is open the wrong way round", path);
    }
    return fd;
  }
  do {
    fd = ::open(path, flags);
  } while (fd < 0 && errno == EINTR);
  if (fd < 0) {
    quitf(_fail, "rbx: cannot open fanout channel %s", path);
  }
  return fd;
}

inline Channel &channel(int i) {
  int n = static_cast<int>(channels().size());
  if (i < 0 || i >= n) {
    quitf(_fail, "rbx: no process %d (there are %d)", i, n);
  }
  return channels()[static_cast<size_t>(i)];
}

} // namespace detail

// How many processes the interactor talks to.
inline int count() { return static_cast<int>(detail::channels().size()); }

// What process i writes, read like `ouf`: malformed output is a wrong answer.
inline InStream &from(int i) { return *detail::channel(i).from; }

// What process i reads. Flush (std::endl) after each message.
inline std::ostream &to(int i) { return *detail::channel(i).to; }

// Closes every channel, so processes still reading see end of file.
inline void close_all() {
  for (auto &c : detail::channels()) {
    if (c.to) {
      c.to->flush();
    }
    if (c.buf) {
      c.buf->closeFd();
    }
    if (c.from) {
      c.from->close();
    }
  }
}

} // namespace fanout

// registerInteraction for an interactor that talks to several processes.
inline void registerFanoutInteraction(int argc, char *argv[]) {
  // `inf` and `tout` exactly as registerInteraction sets them up. It takes at
  // most an answer and a report file after them, so it only sees the first two.
  registerInteraction(3, argv);
  {{CONSUME_GRADER_HEADER}}
  // A process that exits early must not take the interactor down with it.
  std::signal(SIGPIPE, SIG_IGN);
  if (argc < 7 || (argc - 3) % 2 != 0) {
    quitf(_fail,
          "rbx: expected <input> <output> and a <from> <to> pair per process "
          "(at least two), got %d arguments",
          argc - 1);
  }
  int n = (argc - 3) / 2;
  auto &chans = fanout::detail::channels();
  chans.resize(static_cast<size_t>(n));
  for (int i = 0; i < n; i++) {
    const char *fromPath = argv[3 + 2 * i];
    const char *toPath = argv[4 + 2 * i];
    // A CMS sandbox opens a process's stdin before its stdout, so the channel
    // to it must be opened first, or both sides block forever.
    int toFd = fanout::detail::openChannel(toPath, O_WRONLY);
    int fromFd = fanout::detail::openChannel(fromPath, O_RDONLY);
    std::FILE *fromFile = fdopen(fromFd, "rb");
    if (fromFile == nullptr) {
      quitf(_fail, "rbx: cannot read fanout channel %s", fromPath);
    }

    auto &c = chans[static_cast<size_t>(i)];
    c.buf.reset(new fanout::detail::FdBuf(toFd));
    c.to.reset(new std::ostream(c.buf.get()));
    c.from.reset(new InStream());
    c.from->name = "process " + std::to_string(i);
    c.from->mode = _output;
    // testlib reads only the standard streams unbuffered; its buffered reader
    // waits for about 1 MB and would block on a pipe. Marking the stream
    // standard picks the unbuffered one.
    c.from->stdfile = true;
    c.from->reset(fromFile);
  }
}

} // namespace rbx
#endif
