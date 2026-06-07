using Wyb.Ledger.Data;

namespace Wyb.Ledger.Events;

public sealed record TransactionRecorded(string DedupKey,
                                         DateOnly Date,
                                         long AmountMinor,
                                         string Currency,
                                         string RawDescription,
                                         DateTimeOffset ImportedAt,
                                         TransactionCategory Category,
                                         int SchemaVersion);