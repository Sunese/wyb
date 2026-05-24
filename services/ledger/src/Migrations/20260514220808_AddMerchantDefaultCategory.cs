using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Wyb.Ledger.Migrations
{
    /// <inheritdoc />
    public partial class AddMerchantDefaultCategory : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<int>(
                name: "DefaultCategory",
                table: "Merchants",
                type: "integer",
                nullable: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "DefaultCategory",
                table: "Merchants");
        }
    }
}
