using Microsoft.EntityFrameworkCore;

namespace Wyb.Ledger.Data;

public class LedgerDbContext(DbContextOptions<LedgerDbContext> options) : DbContext(options)
{
    public DbSet<Transaction> Transactions => Set<Transaction>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<Transaction>(e =>
        {
            e.HasIndex(t => t.DedupKey).IsUnique();
        });
    }
}
