"""
pylint helper plugin which reports "# expect=symbol,..." annotations

Output is to stdout in the form "<line_number>:<symbol>", one line per expected
symbol instance.  Example output:

    23:missing-await
    33:missing-async-for
    52:not-context-manager
    56:not-context-manager

For easy comparison with pylint runs, the output format of this helper matches
that of pylint when using option --msg-template '{line}:{symbol}'.

This plugin does not itself emit pylint messages.

See https://github.com/PyCQA/pylint/issues/2863, which proposes tighter
integration of this testing approach into pylint.

TODO: support multiple symbols in one annotation
TODO: add target module path to output
"""

import tokenize

from pylint.checkers import BaseTokenChecker
from pylint.interfaces import ITokenChecker


def register(linter):
    linter.register_checker(ExpectedMessageReporter(linter))


PREFIX = '# expect='


class ExpectedMessageReporter(BaseTokenChecker):
    __implements__ = ITokenChecker

    name = 'expect-message'
    msgs = {'W5682': ('', 'unused-w5682', '')}

    def process_tokens(self, tokens):
        for (tok_type, token, (start_row, _), _, _) in tokens:
            if tok_type == tokenize.COMMENT:
                if token.startswith(PREFIX):
                    symbol = token[len(PREFIX):]
                    assert ',' not in symbol, 'multiple symbols not supported'
                    print('%s:%s' % (start_row, symbol))
