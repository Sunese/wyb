using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Wyb.Ledger.Migrations
{
    /// <inheritdoc />
    public partial class DropRulesAndMerchants : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            // MerchantAliases has a FK to Merchants — drop it first.
            migrationBuilder.DropTable(name: "MerchantAliases");
            migrationBuilder.DropTable(name: "Merchants");
            migrationBuilder.DropTable(name: "CategoryRules");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "CategoryRules",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    Name = table.Column<string>(type: "text", nullable: false),
                    Pattern = table.Column<string>(type: "text", nullable: false),
                    MatchType = table.Column<int>(type: "integer", nullable: false),
                    Category = table.Column<int>(type: "integer", nullable: false),
                    Priority = table.Column<int>(type: "integer", nullable: false),
                    CreatedAt = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                },
                constraints: table => table.PrimaryKey("PK_CategoryRules", x => x.Id));

            migrationBuilder.CreateTable(
                name: "Merchants",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    CanonicalName = table.Column<string>(type: "text", nullable: false),
                    DefaultCategory = table.Column<int>(type: "integer", nullable: true),
                },
                constraints: table => table.PrimaryKey("PK_Merchants", x => x.Id));

            migrationBuilder.CreateTable(
                name: "MerchantAliases",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uuid", nullable: false),
                    MerchantId = table.Column<Guid>(type: "uuid", nullable: false),
                    Pattern = table.Column<string>(type: "text", nullable: false),
                    MatchType = table.Column<int>(type: "integer", nullable: false),
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_MerchantAliases", x => x.Id);
                    table.ForeignKey(
                        name: "FK_MerchantAliases_Merchants_MerchantId",
                        column: x => x.MerchantId,
                        principalTable: "Merchants",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_CategoryRules_Priority",
                table: "CategoryRules",
                column: "Priority");

            migrationBuilder.CreateIndex(
                name: "IX_MerchantAliases_MerchantId",
                table: "MerchantAliases",
                column: "MerchantId");
        }
    }
}
