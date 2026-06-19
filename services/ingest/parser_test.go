package main

import (
	"strings"
	"testing"
	"time"
)

func mustParseDate(s string) time.Time {
	t, err := time.Parse("2006-01-02", s)
	if err != nil {
		panic(err)
	}
	return t
}

func TestDecodeToUTF8_PlainUTF8(t *testing.T) {
	input := []byte("Dato;Tekst;Beløb\n")
	got, err := decodeToUTF8(input)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if string(got) != string(input) {
		t.Errorf("plain UTF-8 should be returned unchanged")
	}
}

func TestDecodeToUTF8_BOMStripped(t *testing.T) {
	bom := []byte{0xEF, 0xBB, 0xBF}
	payload := []byte("Dato;Tekst;Beløb\n")
	got, err := decodeToUTF8(append(bom, payload...))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if string(got) != string(payload) {
		t.Errorf("BOM should be stripped; got %q", got)
	}
}

func TestDecodeToUTF8_Windows1252(t *testing.T) {
	// "Beløb" in Windows-1252: ø = 0xF8
	input := []byte("Dato;Tekst;Bel\xf8b\n")
	got, err := decodeToUTF8(input)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := "Dato;Tekst;Beløb\n"
	if string(got) != want {
		t.Errorf("Windows-1252: got %q, want %q", got, want)
	}
}

func TestSniffHeader_Semicolon(t *testing.T) {
	data := []byte("Dato;Tekst;Beløb\n01.01.2026;Test;-100,00\n")
	header, err := sniffHeader(data)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(header) != 3 || header[0] != "Dato" {
		t.Errorf("semicolon: got %v", header)
	}
}

func TestSniffHeader_Comma(t *testing.T) {
	data := []byte("Date,Description,Amount\n2026-01-01,Test,-100\n")
	header, err := sniffHeader(data)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(header) != 3 || header[0] != "Date" {
		t.Errorf("comma: got %v", header)
	}
}

func TestSniffHeader_Tab(t *testing.T) {
	data := []byte("Date\tDescription\tAmount\n2026-01-01\tTest\t-100\n")
	header, err := sniffHeader(data)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(header) != 3 || header[0] != "Date" {
		t.Errorf("tab: got %v", header)
	}
}

func TestSniffHeader_UnknownFormat(t *testing.T) {
	// Single-column lines can't be disambiguated.
	data := []byte("onlyone\nsecondrow\n")
	_, err := sniffHeader(data)
	if err == nil {
		t.Error("expected error for single-column data")
	}
}

// ── danskeParser ─────────────────────────────────────────────────────────────

const danskeCSV = `Dato;Tekst;Beløb;Saldo;Status;Afstemt
04.05.2026;NETFLIX.COM;-119,00;42.199,55;Udført;Ja
06.05.2026;SPOTIFY P0411234567;-99,00;42.100,55;Udført;Ja
04.05.2026;Løn;3.500,00;45.699,55;Udført;Ja
`

func TestDanskeParser_DetectHeader(t *testing.T) {
	p := &danskeParser{}
	if !p.DetectHeader([]string{"Dato", "Tekst", "Beløb", "Saldo", "Status", "Afstemt"}) {
		t.Error("should detect standard Danske Bank header")
	}
	if p.DetectHeader([]string{"Dato", "Kategori", "Underkategori", "Tekst", "Beløb"}) {
		t.Error("should not detect Kategori-format header")
	}
}

func TestDanskeParser_Parse(t *testing.T) {
	p := &danskeParser{}
	rows, err := p.Parse(strings.NewReader(danskeCSV), "test.csv", "salary")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(rows) != 3 {
		t.Fatalf("expected 3 rows, got %d", len(rows))
	}
	if rows[0].Description != "NETFLIX.COM" {
		t.Errorf("description: got %q", rows[0].Description)
	}
	if rows[0].AmountMinor != -11900 {
		t.Errorf("amount: got %d", rows[0].AmountMinor)
	}
	if rows[2].AmountMinor != 350000 {
		t.Errorf("credit amount: got %d", rows[2].AmountMinor)
	}
}

// ── danskeParserWithCategories ────────────────────────────────────────────────

const danskeCatCSV = `Dato;Kategori;Underkategori;Tekst;Beløb;Saldo;Status;Afstemt
18.06.2026;Abonnementer;Streaming;Netflix.Com;-149,00;13.665,48;Udført;Nej
15.06.2026;Ukategoriseret;Ukategoriseret;MobilePay Podimo ApS;-129,00;13.814,48;Udført;Ja
01.06.2026;;;Løn;25.000,00;42.000,00;Udført;Ja
`

func TestDanskeParserWithCategories_DetectHeader(t *testing.T) {
	p := &danskeParserWithCategories{}
	if !p.DetectHeader([]string{"Dato", "Kategori", "Underkategori", "Tekst", "Beløb", "Saldo", "Status", "Afstemt"}) {
		t.Error("should detect Kategori-format header")
	}
	if p.DetectHeader([]string{"Dato", "Tekst", "Beløb", "Saldo", "Status", "Afstemt"}) {
		t.Error("should not detect standard header")
	}
}

func TestDanskeParserWithCategories_Parse(t *testing.T) {
	p := &danskeParserWithCategories{}
	rows, err := p.Parse(strings.NewReader(danskeCatCSV), "budget.csv", "budget")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(rows) != 3 {
		t.Fatalf("expected 3 rows, got %d", len(rows))
	}
	if rows[0].Description != "Netflix.Com" {
		t.Errorf("description: got %q", rows[0].Description)
	}
	if rows[0].AmountMinor != -14900 {
		t.Errorf("amount: got %d, want -14900", rows[0].AmountMinor)
	}
	if rows[2].AmountMinor != 2500000 {
		t.Errorf("credit: got %d", rows[2].AmountMinor)
	}
	if rows[0].AccountID != "budget" {
		t.Errorf("accountID: got %q", rows[0].AccountID)
	}
}

func TestComputeDedupKey_Deterministic(t *testing.T) {
	row := Row{
		AccountID:   "salary",
		Date:        mustParseDate("2026-01-15"),
		AmountMinor: 350000,
		Currency:    "DKK",
		Description: "NETS BETALING",
	}
	a := ComputeDedupKey(row)
	b := ComputeDedupKey(row)
	if a != b {
		t.Errorf("dedup key not deterministic: %q vs %q", a, b)
	}
	if a == "" {
		t.Error("dedup key should not be empty")
	}
}

func TestComputeDedupKey_DiffersAcrossFields(t *testing.T) {
	base := Row{
		AccountID:   "salary",
		Date:        mustParseDate("2026-01-15"),
		AmountMinor: 350000,
		Currency:    "DKK",
		Description: "NETS BETALING",
	}
	cases := []struct {
		name string
		row  Row
	}{
		{"different account", func() Row { r := base; r.AccountID = "savings"; return r }()},
		{"different date", func() Row { r := base; r.Date = mustParseDate("2026-01-16"); return r }()},
		{"different amount", func() Row { r := base; r.AmountMinor = 1; return r }()},
		{"different currency", func() Row { r := base; r.Currency = "EUR"; return r }()},
		{"different description", func() Row { r := base; r.Description = "OTHER"; return r }()},
	}
	baseKey := ComputeDedupKey(base)
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := ComputeDedupKey(c.row); got == baseKey {
				t.Errorf("key collision: %q", got)
			}
		})
	}
}
