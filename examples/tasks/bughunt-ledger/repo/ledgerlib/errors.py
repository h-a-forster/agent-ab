"""Exception hierarchy for ledgerlib."""


class LedgerError(Exception):
    """Base class for all ledgerlib errors."""


class AccountError(LedgerError):
    """Unknown account, duplicate code, or an invalid chart-of-accounts change."""


class UnbalancedEntry(LedgerError):
    """A journal entry whose lines do not sum to zero in every currency."""


class CurrencyMismatch(LedgerError):
    """Arithmetic or posting that mixes currencies."""


class ImportFailure(LedgerError):
    """A row of imported text could not be understood."""

    def __init__(self, message, line=None):
        super().__init__(message if line is None else "line %d: %s" % (line, message))
        self.line = line
