using System.Security.Cryptography;
using System.Text;

namespace Wyb.Ledger.Data;

public static class DedupKey
{
    public static string Compute(string accountId, DateOnly date, long amountMinor, string currency, string rawDescription)
    {
        var normalized = rawDescription.Trim().ToUpperInvariant();
        var input = $"{accountId}|{date:yyyy-MM-dd}|{amountMinor}|{currency}|{normalized}";
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(input));
        return Convert.ToHexStringLower(hash);
    }
}
