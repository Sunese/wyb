package main

import (
	"testing"
	"time"
)

func TestParseDanishAmount(t *testing.T) {
	cases := []struct {
		input string
		want  int64
	}{
		{"-3.842,00", -384200},
		{"22.000,00", 2200000},
		{"-88,00", -8800},
		{"68,00", 6800},
		{"-146,37", -14637},
		{"0,00", 0},
	}

	for _, c := range cases {
		t.Run(c.input, func(t *testing.T) {
			got, err := parseDanishAmount(c.input)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != c.want {
				t.Errorf("parseDanishAmount(%q) = %d, want %d", c.input, got, c.want)
			}
		})
	}
}

func TestDanskeParserDetectHeader(t *testing.T) {
	p := &danskeParser{}

	if !p.DetectHeader([]string{"Dato", "Tekst", "Beløb", "Saldo", "Status", "Afstemt"}) {
		t.Error("should detect valid Danske Bank header")
	}
	if p.DetectHeader([]string{"Date", "Description", "Amount"}) {
		t.Error("should not detect unknown header")
	}
}

func TestDetectParserUnknown(t *testing.T) {
	if detectParser([]string{"Date", "Description", "Amount"}) != nil {
		t.Error("expected nil for unrecognised header")
	}
}

func TestParseDanskeBank(t *testing.T) {
	rows, err := ParseFile("../../testdata/danskebank_salary_20250101_20251231.csv")
	if err != nil {
		t.Fatalf("ParseFile: %v", err)
	}
	if len(rows) == 0 {
		t.Fatal("expected at least one row")
	}

	r := rows[0]
	// Account ID is the filename stem — the full name minus extension and any archive timestamp prefix.
	if r.AccountID != "danskebank_salary_20250101_20251231" {
		t.Errorf("AccountID = %q, want %q", r.AccountID, "danskebank_salary_20250101_20251231")
	}
	if r.Currency != "DKK" {
		t.Errorf("Currency = %q, want DKK", r.Currency)
	}
	if r.Date.IsZero() {
		t.Error("Date should not be zero")
	}
	wantDate := time.Date(2026, 5, 4, 0, 0, 0, 0, time.UTC)
	if !r.Date.Equal(wantDate) {
		t.Errorf("first row Date = %v, want %v", r.Date, wantDate)
	}
	if r.AmountMinor != 350000 {
		t.Errorf("AmountMinor = %d, want 350000", r.AmountMinor)
	}
}

func TestParseDanskeBank_ArchivedFilename(t *testing.T) {
	// Archived files have a timestamp prefix — ParseFile must strip it transparently.
	// We test this by checking that the archived prefix regex strips correctly.
	got := archivedPrefix.ReplaceAllString("20260514T155959Z_salary.csv", "")
	if got != "salary.csv" {
		t.Errorf("archivedPrefix strip: got %q, want %q", got, "salary.csv")
	}
}
