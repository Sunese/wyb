using System.Security.Cryptography;
using System.Text;

namespace Wyb.Ledger.Data;

public static class DedupKey
{
    /// <summary>
    /// Computes a deduplication key for a transaction based on its account ID, date, amount, currency, and raw description.
    /// </summary>
    /// <param name="accountId"></param>
    /// <param name="date"></param>
    /// <param name="amountMinor"></param>
    /// <param name="currency"></param>
    /// <param name="rawDescription"></param>
    /// <returns>
    /// A tuple containing the computed hash (as a lowercase hexadecimal string) and the normalized input string used for hashing.
    /// </returns>
    public static (string hash, string input) Compute(string accountId, DateOnly date, long amountMinor, string currency, string rawDescription)
    {
        var normalized = rawDescription.Trim().ToUpperInvariant();
        var input = $"{accountId}|{date:yyyy-MM-dd}|{amountMinor}|{currency}|{normalized}";
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(input));
        return (Convert.ToHexStringLower(hash), input);
    }
}
