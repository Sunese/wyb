namespace Wyb.Ledger.Events;

public sealed record CategoryOverridden(string DedupKey, TransactionCategory Category);