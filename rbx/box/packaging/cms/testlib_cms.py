"""rbx's testlib, patched to speak CMS's checker protocol.

CMS's Polygon importer compiles `check.cpp` against its own patched testlib
(0.9.21), which prints a `quitp` value verbatim as the outcome -- so rbx's
percentage would score 100 times too much, and CMS does not clamp it -- and hides
the checker's message. `cms_conf.py` builds the checker itself instead, against
this variant of the testlib rbx ships, compiled with `-DRBX_CMS`:

- CMS runs `checker <input> <correct output> <contestant output>`, so the last
  two arguments are swapped back into testlib's order.
- The verdict becomes CMS's: the outcome, a fraction in [0, 1], on stdout, and
  the message on stderr (CMS shows its first line), exiting 0. OK is 1, a wrong
  answer 0 and `quitp(x)` x / 100. A checker failure, `_pc` (which rbx refuses)
  and a percentage outside [0, 100] exit 1, which CMS reports as a judge error.

The patch is applied by anchors and raises when one is missing, so a testlib
upgrade fails a test rather than a package.
"""

CMS_TESTLIB_FILE = 'cms_testlib.h'

_ARGS_ANCHOR = """    argc = int(args.size());
    if (argc > 1 && "--help" == args[1])
        __testlib_help();
"""

_ARGS_PATCH = """    argc = int(args.size());
#ifdef RBX_CMS
    // CMS passes the correct output before the contestant's.
    if (argc >= 4)
        std::swap(args[2], args[3]);
#endif
    if (argc > 1 && "--help" == args[1])
        __testlib_help();
"""

_QUIT_ANCHOR = """    int pctype = result - _partially;
    bool isPartial = false;
"""

_QUIT_PATCH = """#ifdef RBX_CMS
    {
        double rbxCmsOutcome = -1;
        const char *rbxCmsDefault = "";
        std::string rbxCmsMessage = message;
        if (result == _ok) {
            rbxCmsOutcome = 1;
            rbxCmsDefault = "translate:success";
        } else if (result == _wa || result == _pe || result == _dirt ||
                   result == _unexpected_eof) {
            rbxCmsOutcome = 0;
            rbxCmsDefault = "translate:wrong";
        } else if (result == _points && __testlib_points >= 0 &&
                   __testlib_points <= 100) {
            rbxCmsOutcome = __testlib_points / 100;
            rbxCmsDefault = "translate:partial";
            // `quitp` puts the points in front of the message.
            size_t rbxCmsSpace = rbxCmsMessage.find(' ');
            rbxCmsMessage = rbxCmsSpace == std::string::npos
                                ? ""
                                : rbxCmsMessage.substr(rbxCmsSpace + 1);
        }
        if (rbxCmsOutcome < 0) {
            std::fprintf(stderr, "FAIL %s\\n", message.c_str());
            std::exit(1);
        }
        std::fprintf(stdout, "%.10f\\n", rbxCmsOutcome);
        std::fprintf(stderr, "%s\\n",
                     rbxCmsMessage.empty() ? rbxCmsDefault : rbxCmsMessage.c_str());
        std::exit(0);
    }
#endif
    int pctype = result - _partially;
    bool isPartial = false;
"""


def patch(testlib: str) -> str:
    """The CMS variant of `testlib` (the text of a `testlib.h`)."""
    for anchor in (_ARGS_ANCHOR, _QUIT_ANCHOR):
        if testlib.count(anchor) != 1:
            raise ValueError(
                'testlib.h changed: cannot find where to patch it for CMS:\n' + anchor
            )
    return testlib.replace(_ARGS_ANCHOR, _ARGS_PATCH).replace(_QUIT_ANCHOR, _QUIT_PATCH)
