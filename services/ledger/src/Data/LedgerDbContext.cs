using Microsoft.EntityFrameworkCore;

namespace Wyb.Ledger.Data;

public class LedgerDbContext(DbContextOptions<LedgerDbContext> options) : DbContext(options)
{
}
